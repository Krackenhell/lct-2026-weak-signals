"""Разбор ответов каждого открытого источника на записанных образцах (без сети).

Ловит главное, что ломается при изменении API: поля, даты, ссылки, типы источников, язык.
"""
import asyncio
import json

import httpx
import pytest

from app.collectors import arxiv, gdelt, github, habr, hackernews, openalex, wikipedia
from app.collectors.http import NotFound, SourceError
from tests.fakes import FakeWeb, arxiv_feed, habr_rss, openalex_works


def _client(handler):
    web = FakeWeb()
    h = web.client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def run(coro):
    return asyncio.run(coro)


def test_arxiv_atom_is_parsed_to_preprints():
    feed = arxiv_feed([{"id": "2609.00001v2", "title": "Optical  circuit\n switching", "summary": "We propose X.", "date": "2026-09-05"}])
    h = _client(lambda r: httpx.Response(200, text=feed))
    docs = run(arxiv.search(h, "optical circuit switching", 5))
    d = docs[0]
    assert d.url == "https://arxiv.org/abs/2609.00001v2"  # http → https
    assert d.title == "Optical circuit switching"  # пробелы и переносы нормализованы
    assert (d.published, d.source_type, d.collector, d.language) == ("2026-09-05", "preprint", "arxiv", "en")
    assert d.extra["authors"] == ["A. Researcher", "B. Engineer"]


@pytest.mark.parametrize("query, expected", [("tinyml", "all:tinyml"), ("edge ai", 'all:"edge ai"'), ('"quoted" term', 'all:"quoted term"')])
def test_arxiv_phrase_query(query, expected):
    assert arxiv._phrase(query) == expected


def test_openalex_works_abstract_and_types():
    data = openalex_works([
        {"title": "Paper A", "abstract": "tokenized deposits settle instantly", "doi": "https://doi.org/10.1/a", "journal": "J1"},
        {"title": "Preprint B", "abstract": "", "type": "preprint", "url": "https://example.org/b"},
        {"title": "", "abstract": "no title — должен быть отброшен"},
    ])
    h = _client(lambda r: httpx.Response(200, json=data))
    docs = run(openalex.search(h, "tokenized deposits", "2024-01-01", 10))
    assert len(docs) == 2
    assert docs[0].snippet == "tokenized deposits settle instantly"  # аннотация восстановлена из инвертированного индекса
    assert (docs[0].url, docs[0].source_name, docs[0].source_type) == ("https://doi.org/10.1/a", "J1", "science")
    assert docs[1].source_type == "preprint" and docs[1].url == "https://example.org/b"


def test_openalex_yearly_counts_skips_garbage():
    h = _client(lambda r: httpx.Response(200, json={"group_by": [{"key": "2025", "count": 4}, {"key": "unknown", "count": 1}, {"key": "2026", "count": "9"}]}))
    assert run(openalex.yearly_counts(h, "x y")) == {2025: 4, 2026: 9}


def test_openalex_sends_key_and_email(monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "openalex_api_key", "k123")
    monkeypatch.setattr(s, "openalex_email", "a@b.c")
    seen = {}

    def handler(r):
        seen.update(dict(r.url.params))
        return httpx.Response(200, json={"group_by": []})

    run(openalex.yearly_counts(_client(handler), "edge ai"))
    assert seen["api_key"] == "k123" and seen["mailto"] == "a@b.c"
    assert seen["filter"] == 'title_and_abstract.search:"edge ai"'


def test_hackernews_external_link_is_news_otherwise_community():
    data = {"nbHits": 42, "hits": [
        {"objectID": "1", "title": "Startup ships X", "url": "https://www.techcrunch.com/x", "created_at": "2026-08-01T00:00:00Z"},
        {"objectID": "2", "title": "Ask HN: X?", "url": None, "created_at": "2026-08-02T00:00:00Z"},
        {"objectID": "3", "title": "", "url": None},
    ]}
    docs, total = run(hackernews.search(_client(lambda r: httpx.Response(200, json=data)), "x", 0, 10))
    assert total == 42 and len(docs) == 2
    assert docs[0].source_type == "news" and docs[0].source_name == "techcrunch.com (через Hacker News)"
    assert docs[1].source_type == "community" and docs[1].url == "https://news.ycombinator.com/item?id=2"


def test_github_counts_and_repos(monkeypatch):
    from app.config import get_settings

    seen = {}

    def handler(r):
        seen["auth"] = r.headers.get("authorization")
        seen["q"] = r.url.params["q"]
        return httpx.Response(200, json={"total_count": 17, "items": [{"html_url": "https://github.com/a/b", "full_name": "a/b", "description": "d", "created_at": "2026-02-03T00:00:00Z", "stargazers_count": 5}]})

    h = _client(handler)
    assert run(github.count_created(h, "edge ai", "2025-10-01", "2026-10-01")) == 17
    assert seen["q"] == '"edge ai" created:2025-10-01..2026-10-01' and seen["auth"] is None
    monkeypatch.setattr(get_settings(), "github_token", "ghtest")
    repos = run(github.top_repos(_client(handler), "tinyml", 1))
    assert seen["auth"] == "Bearer ghtest"
    assert (repos[0].source_type, repos[0].published, repos[0].extra["stars"]) == ("repository", "2026-02-03", 5)


def test_wikipedia_exact_title_and_average_views():
    def handler(r):
        if "wikimedia.org" in str(r.url):
            return httpx.Response(200, json={"items": [{"views": 100}, {"views": 300}]})
        return httpx.Response(200, json={"query": {"search": [{"title": "Edge AI hardware"}, {"title": "Edge computing"}]}})

    assert run(wikipedia.lookup(_client(handler), "edge computing")) == {"exists": True, "title": "Edge computing", "monthly_views": 200.0}
    # Похожая, но не та статья — считаем, что статьи нет (иначе любой термин выглядел бы «зрелым»).
    assert run(wikipedia.lookup(_client(handler), "edge inference"))["exists"] is False


def test_wikipedia_views_failure_keeps_existence():
    def handler(r):
        if "wikimedia.org" in str(r.url):
            return httpx.Response(404)
        return httpx.Response(200, json={"query": {"search": [{"title": "TinyML"}]}})

    assert run(wikipedia.lookup(_client(handler), "tinyml")) == {"exists": True, "title": "TinyML", "monthly_views": 0.0}


def test_gdelt_languages_and_query():
    seen = {}

    def handler(r):
        seen["q"] = r.url.params["query"]
        return httpx.Response(200, json={"articles": [
            {"url": "https://ria.ru/1", "title": "Новость", "seendate": "20260901T120000Z", "domain": "ria.ru", "language": "Russian"},
            {"url": "", "title": "без ссылки"},
        ]})

    docs = run(gdelt.search(_client(handler), "edge ai", "12m", 10, lang="russian"))
    assert seen["q"] == '"edge ai" sourcelang:russian'
    assert len(docs) == 1 and (docs[0].language, docs[0].published, docs[0].source_name) == ("ru", "2026-09-01", "ria.ru")


def test_gdelt_text_answer_is_source_error(monkeypatch):
    # При превышении лимита GDELT отвечает текстом, а не JSON — это сбой источника, а не пустой результат.
    from app.collectors import http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    h = _client(lambda r: httpx.Response(200, text="Please limit requests"))
    with pytest.raises(SourceError):
        run(gdelt.search(h, "x", "12m", 5))


def test_habr_rss_company_blog_is_press():
    rss = habr_rss([
        {"title": "Федеративное обучение на практике", "link": "https://habr.com/ru/articles/1/", "desc": "<p>текст</p>"},
        {"title": "Наш продукт", "link": "https://habr.com/ru/companies/acme/articles/2/"},
    ])
    docs = run(habr.search(_client(lambda r: httpx.Response(200, text=rss)), "федеративное обучение", 5))
    assert docs[0].url == "https://habr.com/ru/articles/1/" and docs[0].snippet == "текст"  # utm и HTML убраны
    assert (docs[0].source_type, docs[0].language, docs[0].published) == ("news", "ru", "2026-09-01")
    assert docs[1].source_type == "press" and "блог компании" in docs[1].source_name


def test_crossref_dates_jats_and_types():
    from app.collectors import crossref

    data = {"message": {"items": [
        {"DOI": "10.1/a", "title": ["Tokenized  deposits"], "published": {"date-parts": [[2025, 3]]}, "container-title": ["J. Banking"], "type": "journal-article", "abstract": "<jats:p>Pilot <jats:italic>results</jats:italic></jats:p>"},
        {"DOI": "10.1/b", "title": ["Токенизированные депозиты"], "published": {"date-parts": [[2026]]}, "type": "posted-content"},
        {"DOI": "10.1/c", "title": ["Review"], "type": "peer-review"},
        {"title": ["Без DOI"], "type": "journal-article"},
    ]}}
    seen = {}

    def handler(r):
        seen.update(dict(r.url.params))
        return httpx.Response(200, json=data)

    docs = run(crossref.search(_client(handler), '"tokenized deposits"', "2024-01-01", 5))
    assert seen["filter"] == "from-pub-date:2024-01-01" and seen["query.bibliographic"] == "tokenized deposits"
    assert [d.url for d in docs] == ["https://doi.org/10.1/a", "https://doi.org/10.1/b"]  # рецензии и записи без DOI отброшены
    a, b = docs
    assert (a.title, a.snippet, a.published, a.source_name, a.source_type, a.language) == ("Tokenized deposits", "Pilot results", "2025-03-01", "J. Banking", "science", "en")
    assert (b.published, b.source_type, b.language, b.source_name) == ("2026-01-01", "preprint", "ru", "Crossref")


def test_cyberleninka_post_and_html_cleanup():
    from app.collectors import cyberleninka

    seen = {}

    def handler(r):
        seen["method"], seen["body"] = r.method, json.loads(r.content)
        return httpx.Response(200, json={"found": 2, "articles": [
            {"name": "<b>Федеративное</b> обучение", "annotation": "Схема <b>федеративного</b> цикла", "link": "/article/n/fed", "year": 2025, "journal": "Вестник", "authors": ["Иванов И."]},
            {"name": "Старая статья", "link": "/article/n/old", "year": 2015},
        ]})

    docs = run(cyberleninka.search(_client(handler), "федеративное обучение", 10, min_year=2023))
    assert seen["method"] == "POST" and seen["body"] == {"mode": "articles", "q": "федеративное обучение", "size": 10, "from": 0}
    assert len(docs) == 1  # статья старше min_year отброшена
    d = docs[0]
    assert (d.url, d.title, d.snippet, d.published, d.language, d.source_type) == ("https://cyberleninka.ru/article/n/fed", "Федеративное обучение", "Схема федеративного цикла", "2025-01-01", "ru", "science")
    assert d.source_name == "КиберЛенинка: Вестник" and d.extra["authors"] == ["Иванов И."]


def test_europepmc_preprints_and_links():
    from app.collectors import europepmc

    seen = {}

    def handler(r):
        seen["q"] = r.url.params["query"]
        return httpx.Response(200, json={"resultList": {"result": [
            {"id": "1", "source": "MED", "doi": "10.9/x", "title": "Digital pathology", "abstractText": "AI slides", "firstPublicationDate": "2026-09-01", "journalInfo": {"journal": {"title": "Pathology Int"}}},
            {"id": "PPR2", "source": "PPR", "title": "Preprint on pathology", "firstPublicationDate": "2026-08-01"},
        ]}})

    docs = run(europepmc.search(_client(handler), "digital pathology", "2024-01-01", 5))
    assert seen["q"] == '"digital pathology" AND FIRST_PDATE:[2024-01-01 TO 3000-01-01]'
    assert (docs[0].url, docs[0].source_name, docs[0].source_type) == ("https://doi.org/10.9/x", "Pathology Int", "science")
    assert (docs[1].url, docs[1].source_type) == ("https://europepmc.org/article/PPR/PPR2", "preprint")


def test_semantic_scholar_only_with_key(monkeypatch):
    from app.collectors import semanticscholar
    from app.config import get_settings

    calls = []

    def handler(r):
        calls.append(r.headers.get("x-api-key"))
        return httpx.Response(200, json={"data": [
            {"title": "TinyML survey", "year": 2025, "externalIds": {"DOI": "10.7/t"}, "venue": "ACM"},
            {"title": "Arxiv only", "publicationDate": "2026-02-02", "externalIds": {"ArXiv": "2602.1"}},
        ]})

    monkeypatch.setattr(get_settings(), "s2_api_key", "")
    assert run(semanticscholar.search(_client(handler), "tinyml", 2024)) == [] and calls == []  # без ключа — не дёргаем API
    monkeypatch.setattr(get_settings(), "s2_api_key", "s2key")
    docs = run(semanticscholar.search(_client(handler), "tinyml", 2024))
    assert calls == ["s2key"]
    assert (docs[0].url, docs[0].published, docs[0].source_type) == ("https://doi.org/10.7/t", "2025-01-01", "science")
    assert (docs[1].url, docs[1].source_type) == ("https://arxiv.org/abs/2602.1", "preprint")


def test_http_post_is_cached_by_body():
    calls = []

    def handler(r):
        calls.append(json.loads(r.content)["q"])
        return httpx.Response(200, json={"q": calls[-1]})

    h = _client(handler)
    assert run(h.post("https://mock.test/s", {"q": "a"})) == {"q": "a"}
    assert run(h.post("https://mock.test/s", {"q": "a"})) == {"q": "a"}
    assert run(h.post("https://mock.test/s", {"q": "b"})) == {"q": "b"}
    assert calls == ["a", "b"]  # одинаковое тело — из кэша, другое тело — новый запрос


def test_rate_limited_source_is_switched_off_after_one_failed_call(monkeypatch):
    from app.collectors import http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(429)

    h = _client(handler)
    with pytest.raises(SourceError):
        run(h.get("https://api.openalex.org/works", params={"q": 1}, cache=False))
    n = len(calls)
    with pytest.raises(SourceError, match="отключён"):
        run(h.get("https://api.openalex.org/works", params={"q": 2}, cache=False))
    assert len(calls) == n == 3  # второй запрос не ушёл в сеть: источник на охлаждении


def test_long_retry_after_is_not_waited_inside_a_query(monkeypatch):
    from app.collectors import http as http_mod

    sleeps, calls = [], []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)

    def handler(r):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "60"})

    with pytest.raises(SourceError, match="пропускаем"):
        run(_client(handler).get("https://api.openalex.org/works", params={"q": 1}, cache=False))
    assert calls == [1] and sleeps == []  # раньше здесь было 2 × 60 секунд ожидания


def test_http_404_is_not_retried():
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(404)

    with pytest.raises(NotFound):
        run(_client(handler).get("https://mock.test/x", cache=False))
    assert len(calls) == 1


def test_http_cache_serves_repeated_request():
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(200, json={"v": 1})

    h = _client(handler)
    assert run(h.get("https://mock.test/c", params={"a": 1})) == {"v": 1}
    assert run(h.get("https://mock.test/c", params={"a": 1})) == {"v": 1}
    assert len(calls) == 1 and h.stats["mock.test"] == {"ok": 1, "cached": 1, "failed": 0}


def test_exhausted_api_key_falls_back_to_anonymous_quota(monkeypatch):
    from app.collectors import http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    seen = []

    def handler(r):
        seen.append("api_key" in r.url.params)
        return httpx.Response(429) if "api_key" in r.url.params else httpx.Response(200, json={"ok": True})

    assert run(_client(handler).get("https://api.openalex.org/works", params={"api_key": "k", "filter": "x"}, cache=False)) == {"ok": True}
    assert seen == [True, False]
