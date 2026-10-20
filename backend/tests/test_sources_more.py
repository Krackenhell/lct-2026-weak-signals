"""Источники 20.10: PubMed, NASA ADS, bioRxiv/medRxiv, Stack Exchange, ClinicalTrials.gov, SEC EDGAR, Роспатент, ЕИС.
Ответы подделаны в формате реальных API (для Роспатента — по примеру из официальной документации), сеть не нужна."""
import asyncio
import tempfile
from pathlib import Path
from types import SimpleNamespace

import httpx

from app.collectors import market_more, science_more
from app.collectors.http import HttpClient
from app.config import get_settings
from app.pipeline import market


def run(coro):
    return asyncio.run(coro)


def client(handler) -> HttpClient:
    h = HttpClient()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    h._interval = {}
    h._cache_dir = Path(tempfile.mkdtemp())
    return h


def with_keys(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setenv(k, v)
    get_settings.cache_clear()


def test_pubmed(monkeypatch):
    with_keys(monkeypatch, NCBI_API_KEY="test-not-a-key")
    try:
        def h(req: httpx.Request):
            assert req.url.params.get("api_key") == "test-not-a-key"
            if "esearch" in req.url.path:
                assert '"liquid biopsy"[tiab]' in req.url.params["term"]
                return httpx.Response(200, json={"esearchresult": {"count": "4673", "idlist": ["111", "222"]}})
            return httpx.Response(200, json={"result": {"111": {"title": "Liquid biopsy for early cancer detection", "source": "Nat Med",
                                                                "sortpubdate": "2099/02/15 00:00", "epubdate": "2026 May 1"}, "222": {"title": ""}}})
        docs, total = run(science_more.pubmed(client(h), "liquid biopsy"))
        # дата электронной публикации, а не будущего номера журнала
        assert total == 4673 and len(docs) == 1 and docs[0].published == "2026-05-01" and docs[0].source_type == "science"
        assert science_more._pubmed_date({"sortpubdate": "2099/02/15 00:00"}) <= __import__("datetime").date.today().isoformat()
    finally:
        get_settings.cache_clear()


def test_ads(monkeypatch):
    with_keys(monkeypatch, NASA_ADS_TOKEN="test-not-a-key")
    try:
        def h(req: httpx.Request):
            assert req.headers["Authorization"] == "Bearer test-not-a-key" and 'abs:"rhombohedral graphene"' in req.url.params["q"]
            return httpx.Response(200, json={"response": {"numFound": 193, "docs": [
                {"title": ["Superconductivity in rhombohedral graphene"], "doi": ["10.1/x"], "pubdate": "2025-06-00", "pub": "Nature", "doctype": "article"},
                {"title": ["Preprint on graphene"], "bibcode": "2026arXiv", "pubdate": "2026-01-00", "doctype": "eprint"}]}})
        docs, total = run(science_more.ads(client(h), "rhombohedral graphene"))
        assert total == 193 and docs[0].url == "https://doi.org/10.1/x" and docs[0].published == "2025-06-01" and docs[1].source_type == "preprint"
    finally:
        get_settings.cache_clear()


def test_biorxiv_catalog_and_local_search():
    pages = {"biorxiv": [{"title": "Organ-on-a-chip model of liver fibrosis", "abstract": "microfluidic organ on a chip", "doi": "10.1101/1", "date": "2026-10-10",
                          "author_corresponding_institution": "MIT", "category": "bioengineering"}],
             "medrxiv": [{"title": "Unrelated cohort study", "abstract": "", "doi": "10.1101/2", "date": "2026-10-11"}]}

    def h(req: httpx.Request):
        server = req.url.path.split("/")[2]
        return httpx.Response(200, json={"messages": [{"total": "1"}], "collection": pages[server]})
    science_more._CATALOG.update(items=[], loaded_at=0.0)
    run(science_more._load_catalog(client(h), 7))
    assert science_more.catalog_ready()
    docs = science_more.biorxiv("organ-on-a-chip liver")
    assert [d.url for d in docs] == ["https://doi.org/10.1101/1"] and docs[0].source_type == "preprint"
    assert science_more.biorxiv("quantum gravity") == []
    science_more._CATALOG.update(items=[], loaded_at=0.0)


def test_stackexchange(monkeypatch):
    with_keys(monkeypatch, STACKEXCHANGE_KEY="test-not-a-key")
    try:
        def h(req: httpx.Request):
            assert req.url.params["site"] == "physics" and req.url.params["q"] == '"graphene"'
            return httpx.Response(200, json={"items": [{"title": "Why is graphene&#39;s band gap zero?", "link": "https://physics.stackexchange.com/q/1",
                                                        "creation_date": 1760000000, "score": 5, "answer_count": 2}], "has_more": True})
        docs, n = run(science_more.stackexchange(client(h), "graphene", "materials"))
        assert docs[0].title == "Why is graphene's band gap zero?" and docs[0].source_type == "community" and n == 2
    finally:
        get_settings.cache_clear()


def test_clinical_trials():
    def h(req: httpx.Request):
        return httpx.Response(200, json={"totalCount": 2418, "studies": [{"protocolSection": {
            "identificationModule": {"nctId": "NCT01", "briefTitle": "Liquid biopsy screening trial"},
            "statusModule": {"overallStatus": "RECRUITING", "startDateStruct": {"date": "2025-03"}},
            "designModule": {"phases": ["PHASE2"]}, "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Acme Health"}}}}]})
    docs, total = run(market_more.clinical_trials(client(h), "liquid biopsy"))
    d = docs[0]
    assert total == 2418 and d.source_type == "trial" and d.extra["market"] == "pilot" and d.published == "2025-03-01" and "Acme Health" in d.snippet


def test_sec_filings():
    def h(req: httpx.Request):
        assert "AgentsOfMoscow" in req.headers["User-Agent"]
        return httpx.Response(200, json={"hits": {"total": {"value": 3}, "hits": [
            {"_id": "0001-26-000001:x", "_source": {"form": "D", "display_names": ["Acme Batteries Inc (CIK 0001234)"], "ciks": ["0001234"],
                                                     "adsh": "0001-26-000001", "file_date": "2026-04-01"}},
            {"_id": "0002", "_source": {"form": "10-K", "display_names": ["BigCo"], "ciks": ["55"], "adsh": "0002", "file_date": "2026-02-01"}}]}})
    s = get_settings()
    old = s.sec_user_agent
    s.sec_user_agent = "AgentsOfMoscow test@example.com"
    try:
        docs, meta = run(market_more.sec_filings(client(h), "solid-state battery"))
    finally:
        s.sec_user_agent = old
    assert meta["total"] == 3 and meta["by_form"] == {"D": 1, "10-K": 1}
    assert docs[0].title == "Acme Batteries Inc: форма D" and docs[0].extra["market"] == "funding" and docs[1].extra["market"] == "launch"
    assert docs[0].url == "https://www.sec.gov/Archives/edgar/data/1234/000126000001/"


def test_rospatent_documented_format(monkeypatch):
    with_keys(monkeypatch, ROSPATENT_API_KEY="test-not-a-key")
    try:
        def h(req: httpx.Request):
            assert req.method == "POST" and req.headers["Authorization"] == "Bearer test-not-a-key"
            return httpx.Response(200, json={"total": 10538, "hits": [{
                "common": {"publishing_office": "RU", "document_number": "2590760", "kind": "C2", "publication_date": "2016.07.10"},
                "biblio": {"ru": {"title": "Твердотельный аккумулятор", "patentee": [{"name": "ООО Ромашка (RU)"}]}},
                "id": "RU2590760C2_20160710", "dataset": "ru_since_1994",
                "snippet": {"description": "Аккумулятор с <em>твердым</em> электролитом"}}]})
        docs, total = run(market_more.rospatent(client(h), "твердотельный аккумулятор"))
        d = docs[0]
        assert total == 10538 and d.title == "Твердотельный аккумулятор" and d.published == "2016-07-10" and d.source_type == "patent"
        assert "ООО Ромашка" in d.snippet and "<em>" not in d.snippet and d.extra["market"] == "patent"
    finally:
        get_settings.cache_clear()


def test_eis_procurement_rss():
    rss = """<?xml version="1.0" encoding="UTF-8"?><rss><channel>
      <item><title>Закупка № 0373100 — поставка промышленного робота</title><link>/epz/order/notice/ea20/view/common-info.html?regNumber=0373100</link>
      <description><![CDATA[Заказчик: ГБУ «Мосгортех»; начальная цена 1 200 000 руб.]]></description><pubDate>Mon, 19 Oct 2026 10:00:00 +0300</pubDate></item>
    </channel></rss>"""

    def h(req: httpx.Request):
        assert req.url.params["searchString"] == "промышленный робот" and req.url.params["morphology"] == "on"
        return httpx.Response(200, text=rss)
    docs = run(market_more.procurement(client(h), "промышленный робот"))
    d = docs[0]
    assert d.url.startswith("https://zakupki.gov.ru/epz/order") and d.published == "2026-10-19" and d.source_type == "procurement"
    assert d.extra["market"] == "procurement" and "Мосгортех" in d.snippet


def test_unreachable_registry_does_not_stall_market_layer(monkeypatch):
    """Реестр, который не отвечает (как Роспатент и ЕИС из части сетей), не задерживает рыночный слой дольше лимита."""
    async def hang(*a, **k):
        await asyncio.sleep(60)

    async def none(*a, **k):
        return [], {}

    monkeypatch.setattr(market, "REGISTRY_DEADLINE", 0.2)
    monkeypatch.setattr(market_more, "sec_filings", none)
    monkeypatch.setattr(market_more, "rospatent", hang)
    monkeypatch.setattr(market_more, "procurement", hang)
    monkeypatch.setattr(market_more, "lens_patents", hang)
    import time

    class Jev:
        async def ask(self, state, questions):
            return SimpleNamespace(answers={}, ok=True)

    t0 = time.time()
    m = run(market.market_layer(None, Jev(), "smart valves", "умные клапаны", "gas lift", [], {}, 0, 0, None, profile="energy", registries=True))
    assert time.time() - t0 < 2 and m["ladder"]["reached"] is None


def test_lens_patents_titles_and_applicants(monkeypatch):
    with_keys(monkeypatch, LENS_API_TOKEN="test-not-a-key")
    try:
        def h(req: httpx.Request):
            import json as _j
            body = _j.loads(req.content)
            assert req.headers["Authorization"] == "Bearer test-not-a-key" and '"solid state battery"' in str(body["query"])
            return httpx.Response(200, json={"total": 10757, "data": [
                {"lens_id": "058-442", "jurisdiction": "US", "doc_number": "20260321767", "kind": "A1", "date_published": "2026-10-15",
                 "biblio": {"invention_title": [{"text": "METHODS FOR REGENERATION OF SOLID-STATE BATTERIES", "lang": "en"}],
                            "parties": {"applicants": [{"extracted_name": {"value": "William Marsh Rice University"}}]}}},
                {"lens_id": "x", "biblio": {}}]})
        docs, total = run(market_more.lens_patents(client(h), "solid state battery"))
        d = docs[0]
        assert total == 10757 and len(docs) == 1 and d.title == "Methods for regeneration of solid-state batteries"
        assert d.extra["applicants"] == ["William Marsh Rice University"] and d.extra["market"] == "patent" and d.published == "2026-10-15"
    finally:
        get_settings.cache_clear()


def test_sec_skipped_without_user_agent():
    s = get_settings()
    old, s.sec_user_agent = s.sec_user_agent, ""
    try:
        def h(req):  # pragma: no cover — запрос не должен уйти
            raise AssertionError("SEC без User-Agent отвечает 403 — запрос не нужен")
        docs, meta = run(market_more.sec_filings(client(h), "x"))
        assert docs == [] and meta["total"] == 0
    finally:
        s.sec_user_agent = old


def test_unreachable_registry_is_remembered_between_runs():
    """Роспатент висит 50 с из части сетей: после таймаута хост пропускается и в следующих прогонах, без новых ожиданий."""
    from app.collectors import http as http_mod

    calls = []

    def h(req):
        calls.append(1)
        raise httpx.ReadTimeout("timeout", request=req)
    http_mod._DOWN.clear()
    try:
        c = client(h)
        for _ in range(2):
            try:
                run(c.post(market_more.RP, {"q": "x"}, cache=False))
            except Exception as exc:  # noqa: BLE001
                assert str(exc)
        assert len(calls) == 1 and http_mod.host_down("searchplatform.rospatent.gov.ru")
    finally:
        http_mod._DOWN.clear()


def test_russian_ca_bundle_loaded():
    """Сертификат УЦ Минцифры встроен: ЕИС и GigaChat проверяются по нему, а не с отключённой проверкой."""
    from app.collectors import http as http_mod

    assert http_mod.CA_BUNDLE.exists() and "BEGIN CERTIFICATE" in http_mod.CA_BUNDLE.read_text()
    ctx = http_mod.ssl_context()
    assert any("Russian Trusted Root CA" in str(c.get("subject")) for c in ctx.get_ca_certs())
    assert get_settings().gigachat_verify_ssl is True


def test_slug_names_from_llm_are_restored():
    from app.pipeline.discovery import clean_name

    assert clean_name("halide-electrolytes-for-all-solid-state-batteries") == "halide electrolytes for all-solid-state batteries"
    assert clean_name("solid-polymer-electrolytes") == "solid polymer electrolytes"
    assert clean_name("sulphide-based solid-state batteries") == "sulphide-based solid-state batteries"  # обычное название не трогаем
    assert clean_name("li-ion") == "li-ion"


def test_not_found_is_an_answer_not_a_failure():
    """EPO отвечает 404, когда патентов нет: это ответ источника, а не сбой (раньше 60 из 77 «сбоев» на прогоне)."""
    c = client(lambda req: httpx.Response(404))
    try:
        run(c.get("https://ops.epo.org/3.2/rest-services/published-data/search", cache=False))
    except Exception:  # noqa: BLE001 — NotFound ожидаем
        pass
    assert c.stats["ops.epo.org"] == {"ok": 1, "cached": 0, "failed": 0}


def test_proxy_routing_by_host_with_direct_fallback(monkeypatch):
    """Российские госсайты — через российский прокси, остальное напрямую; упал прокси — запрос уходит напрямую."""
    from app.collectors import http as http_mod

    monkeypatch.setenv("RU_PROXY_URL", "http://user:pass@127.0.0.1:9")
    monkeypatch.setenv("RU_PROXY_HOSTS", "zakupki.gov.ru")
    get_settings.cache_clear()
    http_mod._PROXY_FAILS.clear()
    http_mod._PROXY_OFF_UNTIL.clear()
    try:
        assert http_mod.proxy_routes() == {"zakupki.gov.ru": "http://user:pass@127.0.0.1:9"}
        c = HttpClient()
        c._cache_dir = Path(tempfile.mkdtemp())
        c._interval = {}

        def proxy_down(req):
            raise httpx.ProxyError("proxy refused", request=req)
        c._client = httpx.AsyncClient(transport=httpx.MockTransport(proxy_down))
        c._direct = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, text="<rss></rss>")))
        for _ in range(3):
            assert run(c.get("https://zakupki.gov.ru/epz/order/extendedsearch/rss.html", as_json=False, cache=False)) == "<rss></rss>"
        assert http_mod._PROXY_OFF_UNTIL.get("zakupki.gov.ru", 0) > 0  # после трёх сбоев прокси хост временно ходит напрямую
    finally:
        get_settings.cache_clear()
        http_mod._PROXY_FAILS.clear()
        http_mod._PROXY_OFF_UNTIL.clear()
