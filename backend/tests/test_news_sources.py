"""Отраслевые новости: RSS-ленты изданий с проверкой robots.txt, SiliconANGLE, события о раундах, доверие по изданию."""
import asyncio

import httpx
import pytest

from app.collectors import news_search, robots
from app.collectors.base import RawDoc
from app.pipeline import passport as pp
from app.pipeline.evidence import Evidence, evidence_items
from app.pipeline.trust import classify
from tests.fakes import FakeWeb, habr_rss


def _client(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize("text, url, ok", [
    ("User-agent: *\nDisallow: /rss/\n", "https://www.finextra.com/rss/headlines.aspx", False),
    ("User-agent: *\nDisallow: /rss/\n", "https://www.finextra.com/news/x", True),
    ("User-agent: *\nDisallow: /?s=\n", "https://techcrunch.com/?s=agentic+payments&feed=rss2", False),
    ("User-agent: *\nDisallow: /?s=\n", "https://techcrunch.com/category/fintech/feed/", True),
    # Google News: всё закрыто, кроме перечисленных страниц; RSS-поиска среди них нет
    ("User-agent: *\nDisallow: /\nAllow: /$\nAllow: /topics/\n", "https://news.google.com/rss/search?q=x", False),
    ("User-agent: *\nDisallow: /\nAllow: /$\nAllow: /topics/\n", "https://news.google.com/topics/abc", True),
    ("User-agent: *\nDisallow: /*?ref=*\n", "https://vc.ru/rss?ref=1", False),
    ("User-agent: *\nDisallow: /my$\n", "https://vc.ru/my/feed", True),  # «$» — точный конец пути
    ("User-agent: *\nDisallow:\n", "https://siliconangle.com/?s=x&feed=rss2", True),  # пустой Disallow — разрешено всё
    ("User-agent: *\nDisallow: /a\nAllow: /a/feed\n", "https://x.com/a/feed/", True),  # побеждает более длинное правило
    # Своя группа агента важнее «*»: закрытие для других ботов нас не касается, а для нас — касается
    ("User-agent: GPTBot\nDisallow: /\n\nUser-agent: *\nDisallow: /wp-json/\n", "https://x.com/feed/", True),
    (f"User-agent: {robots.AGENT}\nUser-agent: other\nDisallow: /feed/\n\nUser-agent: *\nDisallow:\n", "https://x.com/feed/", False),
])
def test_robots_rules(text, url, ok):
    assert robots.is_allowed(robots.parse(text), url) is ok


def test_feeds_skip_what_robots_forbid():
    web = FakeWeb()
    http = web.client()
    docs = run(news_search.industry_feeds(http, "en"))
    assert not any(p.startswith("www.finextra.com") and p != "www.finextra.com/robots.txt" for p in web.feed_paths)
    assert http.stats["www.finextra.com"]["robots_blocked"] == 1  # отказ виден в статистике запуска
    assert {d.source_name for d in docs} >= {"TechCrunch", "The Block", "PR Newswire"}
    d = next(d for d in docs if d.source_name == "TechCrunch" and "raises" in d.title)
    assert (d.collector, d.extra["publisher_domain"], d.extra["event"], d.published) == ("rss", "techcrunch.com", "funding", "2026-09-01")
    assert "utm_" not in d.url


def test_unreachable_robots_means_no_request():
    calls = []

    def handler(r):
        calls.append(r.url.path)
        return httpx.Response(503)

    assert run(news_search.matching(_client(handler), ["x y"], "ru")) == []
    assert all(p == "/robots.txt" for p in calls)  # правила не проверены — ленту не трогаем


def test_select_keeps_only_topic_news():
    mk = lambda t, ev=None: RawDoc(url=f"https://x.com/{abs(hash(t))}", title=t, extra={"event": ev})  # noqa: E731
    docs = [mk("Agentic payments startup raises $30M", "funding"), mk("Visa expands agentic commerce for payments"),
            mk("Quarterly earnings beat expectations"), mk("New payments app launches", "launch"), mk("Сбер запустил агентные платежи", "launch")]
    got = news_search.select(docs, ["agentic payments", "agentic commerce"], n=10)
    # при равном числе совпадений выше новость о раунде
    assert [d.title for d in got] == ["Agentic payments startup raises $30M", "Visa expands agentic commerce for payments"]
    assert len(got) == 2  # одно слово «payments» — мало; общие новости не проходят
    ru = news_search.select(docs, ["агентные платежи"], n=10)
    assert [d.title for d in ru] == ["Сбер запустил агентные платежи"]  # «платежей/платежи» по основе слова


def test_siliconangle_search():
    seen = {}

    def handler(r):
        if r.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow:\n")
        seen["url"] = str(r.url)
        return httpx.Response(200, text=habr_rss([{"title": "Startup raises $20M for agent payments", "link": "https://siliconangle.com/2026/09/01/x/", "desc": "<p>funding</p>"}]))

    docs = run(news_search.siliconangle(_client(handler), "agentic commerce", 5))
    assert "s=agentic+commerce&feed=rss2" in seen["url"]
    assert docs[0].url == "https://siliconangle.com/2026/09/01/x/" and docs[0].extra["event"] == "funding"
    assert docs[0].extra["publisher_domain"] == "siliconangle.com"


@pytest.mark.parametrize("title, event", [
    ("Acme raises $12M Series A to build tokenized deposits", "funding"),
    ("Seed round: robotics startup secures $3 million", "funding"),
    ("Visa acquires agentic payments startup", "funding"),
    ("Стартап привлек 500 млн рублей в раунде A", "funding"),
    ("Mastercard launches agent pay pilot", "launch"),
    ("Сбер представил платформу", "launch"),
    ("Why agentic commerce matters", None),
])
def test_event_detection(title, event):
    assert news_search.event_of(title) == event


def test_trust_uses_publisher_not_feed_address():
    d = RawDoc(url="https://feeds.example.com/x", title="t", source_name="Reuters", source_type="news", collector="rss",
               extra={"publisher_domain": "reuters.com"})
    assert classify(d)[1] == "high"
    pr = RawDoc(url="https://feeds.example.com/y", title="t", source_name="PR Newswire", source_type="news", collector="rss",
                extra={"publisher_domain": "prnewswire.com"})
    assert classify(pr)[0] == "press" and classify(pr)[1] == "low"  # пресс-релиз остаётся пресс-релизом


def test_passport_counts_publishers_and_funding_news():
    items = [
        {"type": "news", "url": "https://feeds.example.com/a", "domain": "techcrunch.com", "event": "funding"},
        {"type": "news", "url": "https://feeds.example.com/b", "domain": "finextra.com", "event": None},
        {"type": "news", "url": "https://feeds.example.com/c", "domain": "reuters.com", "event": "launch"},
    ]
    answers = {f"doc_{i}": {"value": 0.9} for i in (1, 2, 3)} | {"event": {"value": 1 / 6}}
    p = pp.passport(items, answers, 3)
    assert p["domains"] == 3  # три разных издания, а не один адрес ленты
    assert p["event"] == "раунд инвестиций / сделка" and p["hard_event"] and p["funding_news"] == 1
    assert p["level"] == "B"  # нет науки, но три независимых издания и твёрдое событие


def test_event_news_are_not_crowded_out_by_papers():
    papers = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"Paper {i}", source_type="preprint", published="2026-01-01") for i in range(15)]
    news = [RawDoc(url="https://feeds.example.com/z", title="Startup raises $5M", source_type="news", extra={"event": "funding", "publisher_domain": "techcrunch.com"})]
    items = evidence_items(Evidence("x", docs=papers + news), limit=12)
    assert len(items) == 12 and any(i["event"] == "funding" and i["domain"] == "techcrunch.com" for i in items)


def test_llm_reads_industry_news_even_with_many_papers():
    from app.llm.providers import LLMResult, NoLLM
    from app.pipeline import discovery

    class Recorder(NoLLM):
        provider, model = "gigachat", "GigaChat-2"

        def __init__(self):
            super().__init__()
            self.seen = []

        async def complete(self, system, user, temperature=0.2, max_tokens=1500):
            self.seen.append(user)
            return LLMResult("[]", self.provider, self.model, 1, ok=True)

    papers = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"Paper {i}", source_type="preprint", published="2026-01-01") for i in range(400)]
    news = [RawDoc(url=f"https://feeds.example.com/{i}", title=f"Startup {i} raises $5M for agent payments", source_type="news",
                   collector="rss", extra={"event": "funding"}) for i in range(5)]
    llm = Recorder()
    asyncio.run(discovery.llm_candidates(llm, "fintech", papers + news))
    text = "\n".join(llm.seen)
    assert all(f"Startup {i} raises" in text for i in range(5))  # новости дошли до модели, несмотря на 400 статей
    assert sum(t.count("Paper ") for t in llm.seen) <= discovery.MAX_LLM_DOCS - 5


def test_llm_reads_every_subquery_not_just_the_first():
    from app.llm.providers import LLMResult, NoLLM
    from app.pipeline import discovery

    class Recorder(NoLLM):
        provider, model = "gigachat", "GigaChat-2"

        def __init__(self):
            super().__init__()
            self.seen = []

        async def complete(self, system, user, temperature=0.2, max_tokens=1500):
            self.seen.append(user)
            return LLMResult("[]", self.provider, self.model, 1, ok=True)

    # 12 подтем по 60 свежих статей: мест меньше, чем статей, — последняя подтема всё равно должна дойти до модели
    docs = [RawDoc(url=f"https://arxiv.org/abs/{g}-{i}", title=f"Topic{g} paper {i}", source_type="preprint", published="2026-01-01",
                   extra={"group": f"sub{g}"}) for g in range(12) for i in range(60)]
    llm = Recorder()
    asyncio.run(discovery.llm_candidates(llm, "ai infrastructure", docs))
    text = "\n".join(llm.seen)
    per_group = [text.count(f"Topic{g} paper") for g in range(12)]
    assert min(per_group) >= 15 and max(per_group) - min(per_group) <= 1


def test_topic_feeds_and_tag_feeds():
    web = FakeWeb()
    http = web.client()
    docs = run(news_search.for_topic(http, "перспективные решения в финтехе fintech", ["agentic payments", "Neuromorphic event cameras"], "en", 100))
    assert "techcrunch.com/category/fintech/feed/" in web.feed_paths  # тематическая лента области
    assert "techcrunch.com/tag/agentic-payments/feed/" in web.feed_paths  # лента тега, а не закрытый поиск /?s=
    assert not any("?s=" in p for p in web.feed_paths)
    assert any("Neuromorphic event cameras" in d.title for d in docs)
    assert len({d.url for d in docs}) == len(docs)


def test_missing_tag_does_not_trip_breaker():
    def handler(r):
        return httpx.Response(404)

    http = _client(handler)
    assert run(news_search.tag_feeds(http, ["no such tag", "another", "third", "fourth"])) == []
    assert http._fails.get("techcrunch.com", 0) == 0  # 404 — «тега нет», а не сбой источника


def test_chinese_terms_and_events():
    mk = lambda t: RawDoc(url=f"https://x.cn/{abs(hash(t))}", title=t, language="zh", extra={"event": news_search.event_of(t)})  # noqa: E731
    docs = [mk("某公司人形机器人完成A轮融资"), mk("手机新品发布会"), mk("人形机器人研发中心落地")]
    got = news_search.select(docs, ["人形机器人研发"], n=10)
    assert [d.title for d in got] == ["人形机器人研发中心落地", "某公司人形机器人完成A轮融资"]
    assert docs[0].extra["event"] == "funding" and docs[1].extra["event"] == "launch"


def test_country_counts_and_geography():
    import httpx as _httpx

    from app.collectors import openalex

    def handler(r):
        assert r.url.params["group_by"] == "authorships.institutions.country_code"
        assert "publication_year:2024-" in r.url.params["filter"]
        return _httpx.Response(200, json={"group_by": [{"key": "https://openalex.org/countries/CN", "count": 50}, {"key": "US", "count": 30},
                                                       {"key": "RU", "count": 2}, {"key": "unknown", "count": 9}]})

    h = FakeWeb().client()
    h._client = _httpx.AsyncClient(transport=_httpx.MockTransport(handler))
    counts = asyncio.run(openalex.country_counts(h, "humanoid robot", 2024))
    assert counts == {"CN": 50, "US": 30, "RU": 2}
    g = pp.geography(counts)
    assert g["leader"] == "Китай" and g["china"] == round(50 / 82, 3) and g["russia"] == round(2 / 82, 3)
    assert pp.geography({"US": 3}) is None  # по трём работам доли не считаем
