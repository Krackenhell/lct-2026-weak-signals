"""Отраслевые новости: Google News (EN/RU), SiliconANGLE, события о раундах и запусках, доверие по изданию."""
import asyncio

import httpx
import pytest

from app.collectors import news_search
from app.collectors.base import RawDoc
from app.pipeline import passport as pp
from app.pipeline.evidence import Evidence, evidence_items
from app.pipeline.trust import classify
from tests.fakes import FakeWeb, google_news_rss, habr_rss


def _client(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def run(coro):
    return asyncio.run(coro)


def test_google_news_parsing_and_publisher():
    seen = {}

    def handler(r):
        seen.update(dict(r.url.params))
        return httpx.Response(200, text=google_news_rss([
            {"title": "Stripe agentic commerce revs up", "publisher": "Payments Dive", "domain": "paymentsdive.com"},
            {"title": "Agentic payments startup raises $30M Series B", "publisher": "TechCrunch", "domain": "techcrunch.com"},
        ]))

    docs = run(news_search.google_news(_client(handler), '"agentic commerce"', "en", 10))
    assert seen["q"] == "agentic commerce" and seen["hl"] == "en-US" and seen["ceid"] == "US:en"
    a, b = docs
    assert a.title == "Stripe agentic commerce revs up"  # издание убрано из заголовка
    assert (a.source_name, a.extra["publisher_domain"], a.published, a.language, a.collector) == ("Payments Dive", "paymentsdive.com", "2026-09-01", "en", "googlenews")
    assert a.url.startswith("https://news.google.com/") and a.extra["via"] == "Google News"
    assert a.extra["event"] is None and b.extra["event"] == "funding"


def test_google_news_russian():
    seen = {}

    def handler(r):
        seen.update(dict(r.url.params))
        return httpx.Response(200, text=google_news_rss([{"title": "Сбер запустил пилот агентных платежей", "publisher": "РБК", "domain": "rbc.ru"}]))

    docs = run(news_search.google_news(_client(handler), "агентные платежи", "ru", 5))
    assert seen["hl"] == "ru" and seen["ceid"] == "RU:ru"
    assert docs[0].language == "ru" and docs[0].extra["event"] == "launch" and docs[0].source_name == "РБК"


def test_siliconangle_search():
    seen = {}

    def handler(r):
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


def test_trust_uses_publisher_not_google_redirect():
    d = RawDoc(url="https://news.google.com/rss/articles/x", title="t", source_name="Reuters", source_type="news", collector="googlenews",
               extra={"publisher_domain": "reuters.com"})
    assert classify(d)[1] == "high"
    pr = RawDoc(url="https://news.google.com/rss/articles/y", title="t", source_name="PR Newswire", source_type="news", collector="googlenews",
                extra={"publisher_domain": "prnewswire.com"})
    assert classify(pr)[0] == "press" and classify(pr)[1] == "low"  # пресс-релиз остаётся пресс-релизом


def test_passport_counts_publishers_and_funding_news():
    items = [
        {"type": "news", "url": "https://news.google.com/a", "domain": "techcrunch.com", "event": "funding"},
        {"type": "news", "url": "https://news.google.com/b", "domain": "finextra.com", "event": None},
        {"type": "news", "url": "https://news.google.com/c", "domain": "reuters.com", "event": "launch"},
    ]
    answers = {f"doc_{i}": {"value": 0.9} for i in (1, 2, 3)} | {"event": {"value": 1 / 6}}
    p = pp.passport(items, answers, 3)
    assert p["domains"] == 3  # три разных издания, а не один news.google.com
    assert p["event"] == "раунд инвестиций / сделка" and p["hard_event"] and p["funding_news"] == 1
    assert p["level"] == "B"  # нет науки, но три независимых издания и твёрдое событие


def test_event_news_are_not_crowded_out_by_papers():
    papers = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"Paper {i}", source_type="preprint", published="2026-01-01") for i in range(15)]
    news = [RawDoc(url="https://news.google.com/z", title="Startup raises $5M", source_type="news", extra={"event": "funding", "publisher_domain": "techcrunch.com"})]
    items = evidence_items(Evidence("x", docs=papers + news), limit=12)
    assert len(items) == 12 and any(i["event"] == "funding" and i["domain"] == "techcrunch.com" for i in items)
