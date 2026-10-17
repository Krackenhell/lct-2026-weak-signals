"""Госгранты NIH, NSF, UKRI: разбор ответов API, событие «грант» в паспорте и в доказательствах."""
import asyncio
import json

import httpx

from app.collectors import grants
from app.collectors.base import RawDoc
from app.pipeline import passport as pp
from app.pipeline.evidence import Evidence, evidence_items
from app.pipeline.trust import classify
from tests.fakes import FakeWeb


def _client(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def run(coro):
    return asyncio.run(coro)


def test_nih_parsing_and_yearly_counts():
    bodies = []

    def handler(r):
        body = json.loads(r.content)
        bodies.append(body)
        if body["limit"] == 1:
            return httpx.Response(200, json={"meta": {"total": {2024: 3, 2025: 9}[body["criteria"]["fiscal_years"][0]]}, "results": []})
        return httpx.Response(200, json={"meta": {"total": 1}, "results": [{
            "appl_id": 111, "fiscal_year": 2026, "project_title": "Digital twin of the aging heart", "award_amount": 636431,
            "organization": {"org_name": "CLEVELAND CLINIC"}, "agency_ic_admin": {"abbreviation": "NIA"}, "project_start_date": "2026-01-01T00:00:00"}]})

    http = _client(handler)
    d = run(grants.nih(http, '"digital twin"', [2026]))[0]
    assert bodies[0]["criteria"]["advanced_text_search"]["search_text"] == '"digital twin"'
    assert (d.url, d.published, d.source_type, d.extra["event"]) == ("https://reporter.nih.gov/project-details/111", "2026-01-01", "grant", "grant")
    assert "NIA" in d.source_name and "$636,431" in d.snippet
    assert run(grants.nih_yearly(http, "digital twin", [2024, 2025])) == {"2024": 3, "2025": 9}


def test_nsf_and_ukri_parsing():
    def handler(r):
        if r.url.host == "api.nsf.gov":
            assert r.url.params["keyword"] == '"edge ai"'
            return httpx.Response(200, json={"response": {"award": [{"id": "2401234", "title": "Edge AI for sensors", "startDate": "09/01/2025",
                                                                     "fundsObligatedAmt": "300000", "awardeeName": "MIT"}]}})
        return httpx.Response(200, json={"facetedSearchResultBean": {"results": [
            {"projectComposition": {"project": {"id": "A", "title": "Old project", "grantReference": "EP/1", "fund": {"start": 946684800000, "funder": {"name": "EPSRC"}}}}},
            {"projectComposition": {"project": {"id": "B", "title": "Edge AI chips", "grantReference": "EP/2", "grantCategory": "Research Grant",
                                                "fund": {"start": 1735689600000, "valuePounds": 500000, "funder": {"name": "EPSRC"}}},
                                    "leadResearchOrganisation": {"name": "University of Bristol"}}}]}})

    http = _client(handler)
    n = run(grants.nsf(http, "edge ai"))[0]
    assert (n.url, n.published, n.collector) == ("https://www.nsf.gov/awardsearch/showAward?AWD_ID=2401234", "2025-09-01", "nsf")
    u = run(grants.ukri(http, "edge ai", min_year=2020))
    assert [x.title for x in u] == ["Edge AI chips"]  # проект 2000 года отброшен
    assert u[0].url == "https://gtr.ukri.org/projects?ref=EP/2" and "EPSRC" in u[0].source_name


def test_grant_is_trusted_and_raises_event_level():
    g = RawDoc(url="https://reporter.nih.gov/project-details/1", title="t", source_type="grant", collector="nih", extra={"event": "grant"})
    assert classify(g)[:2] == ("grant", "high")
    items = [{"type": "grant", "url": "https://reporter.nih.gov/project-details/1", "event": "grant"},
             {"type": "science", "url": "https://doi.org/10.1/x", "event": None}]
    p = pp.passport(items, {"doc_1": {"value": 0.9}, "doc_2": {"value": 0.9}, "event": {"value": 1 / 6}}, 2)
    assert p["event"] == "грант / госфинансирование" and p["grants"] == 1 and not p["hard_event"]


def test_grant_does_not_crowd_out_market_events():
    papers = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"P{i}", source_type="preprint", published="2026-01-01") for i in range(15)]
    news = [RawDoc(url=f"https://techcrunch.com/{i}", title=f"N{i}", source_type="news", extra={"event": "funding"}) for i in range(3)]
    gr = [RawDoc(url=f"https://reporter.nih.gov/project-details/{i}", title=f"G{i}", source_type="grant", extra={"event": "grant"}) for i in range(3)]
    items = evidence_items(Evidence("x", docs=papers + gr + news), limit=12)
    assert [i["event"] for i in items if i["event"]] == ["funding", "funding", "grant"]
