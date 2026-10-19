"""Стартапы Y Combinator: поиск по описаниям, ряд по годам набора, доверие."""
import asyncio

import httpx

from app.collectors import yc
from app.collectors.base import RawDoc
from app.pipeline.trust import classify
from tests.fakes import FakeWeb

COMPANIES = [
    {"name": "PayBot", "slug": "paybot", "one_liner": "Agentic payments for online stores", "long_description": "", "tags": ["Fintech"], "batch": "Winter 2025", "status": "Active"},
    {"name": "AgentPay", "slug": "agentpay", "one_liner": "Payment rails for AI agents", "long_description": "We build agent payment APIs", "tags": [], "batch": "Summer 2024", "status": "Active"},
    {"name": "Old", "slug": "old", "one_liner": "Agentic payment checkout", "long_description": "", "tags": [], "batch": "Summer 2019", "status": "Inactive"},
    {"name": "Noise", "slug": "noise", "one_liner": "Payments for agencies", "long_description": "", "tags": [], "batch": "Fall 2025", "status": "Active"},
]


def _client():
    calls = []

    def handler(r):
        calls.append(r.url.host)
        return httpx.Response(200, json=COMPANIES)

    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h, calls


def test_search_matches_whole_words_and_sorts_by_batch():
    http, calls = _client()
    docs = asyncio.run(yc.search(http, "agentic payments", 5))
    assert [d.title.split(":")[0] for d in docs] == ["PayBot", "Old"]  # «agencies» и «agent» — не «agentic»
    d = docs[0]
    assert (d.published, d.source_type, d.extra["event"], d.extra["batch"]) == ("2025-01-01", "startup", "startup", "Winter 2025")  # стартап в акселераторе, а не раунд инвестиций
    assert d.url == "https://www.ycombinator.com/companies/paybot"
    assert [x.title.split(":")[0] for x in asyncio.run(yc.search(http, "agentic payments", 5, min_year=2024))] == ["PayBot"]
    assert calls == ["yc-oss.github.io"]  # каталог загружен один раз на процесс


def test_yearly_series_and_parallel_load():
    http, calls = _client()

    async def both():
        return await asyncio.gather(yc.yearly(http, "agent payment"), yc.yearly(http, "agent payment"))

    a, b = asyncio.run(both())
    assert a == b == {"2024": 1}
    assert len(calls) == 1  # параллельные проверки ждут первую загрузку, а не качают 10 МБ каждая


def test_batch_dates_and_trust():
    assert yc.batch_date("Summer 2021") == "2021-06-01" and yc.batch_date("Fall 2024") == "2024-09-01" and yc.batch_date(None) is None
    doc = RawDoc(url="https://www.ycombinator.com/companies/x", title="t", source_type="startup", collector="yc")
    assert classify(doc)[:2] == ("startup", "medium")
