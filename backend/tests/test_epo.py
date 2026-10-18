"""Патенты EPO OPS: без ключа — ни одного запроса; с ключом — токен, счётчики всего и по Китаю."""
import asyncio

import httpx

from app.collectors import epo
from app.config import get_settings
from tests.fakes import FakeWeb


def _client(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def _ops(total: int, refs: list[tuple[str, str, str]]) -> dict:
    return {"ops:world-patent-data": {"ops:biblio-search": {"@total-result-count": str(total), "ops:search-result": {"ops:publication-reference": [
        {"document-id": {"country": {"$": c}, "doc-number": {"$": n}, "kind": {"$": k}}} for c, n, k in refs]}}}}


def test_disabled_without_key_makes_no_requests():
    calls = []
    http = _client(lambda r: calls.append(r) or httpx.Response(500))
    assert not epo.enabled()
    assert asyncio.run(epo.patent_counts(http, "humanoid robot")) is None
    assert asyncio.run(epo.search(http, "humanoid robot")) == []
    assert calls == []


def test_counts_and_docs_with_key(monkeypatch):
    monkeypatch.setenv("EPO_OPS_KEY", "k")
    monkeypatch.setenv("EPO_OPS_SECRET", "s")
    get_settings.cache_clear()
    epo._TOKEN.clear()
    seen = []

    def handler(r):
        if r.url.path.endswith("/accesstoken"):
            assert r.headers["Authorization"].startswith("Basic ")
            return httpx.Response(200, json={"access_token": "T", "expires_in": "1199"})
        assert r.headers["Authorization"] == "Bearer T"
        q = r.url.params["q"]
        seen.append(q)
        if "pn=CN" in q:
            return httpx.Response(200, json=_ops(60, []))
        return httpx.Response(200, json=_ops(100, [("CN", "118000001", "A"), ("US", "2025123", "A1")]))

    try:
        http = _client(handler)
        c = asyncio.run(epo.patent_counts(http, "humanoid robot"))
        assert c["total"] == 100 and c["china"] == 60 and c["china_share"] == 0.6
        assert seen[0].startswith('ta="humanoid robot" and pd>=')
        docs = asyncio.run(epo.search(http, "humanoid robot", 2))
        assert [d.extra["country"] for d in docs] == ["CN", "US"] and docs[0].source_type == "patent"
        assert "pn%3DCN118000001A" in docs[0].url
    finally:
        monkeypatch.delenv("EPO_OPS_KEY")
        monkeypatch.delenv("EPO_OPS_SECRET")
        get_settings.cache_clear()
