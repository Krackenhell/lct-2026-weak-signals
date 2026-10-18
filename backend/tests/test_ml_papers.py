"""Hugging Face Papers и OpenReview: разбор ответов, отсечение старых работ, сортировка по свежести."""
import asyncio

import httpx

from app.collectors import ml_papers
from tests.fakes import FakeWeb


def _client(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def test_hf_papers():
    def handler(r):
        assert r.url.params["q"] == "humanoid robot"
        return httpx.Response(200, json=[
            {"paper": {"id": "2312.06571", "title": "Alter3 humanoid", "summary": "old", "publishedAt": "2023-12-11T17:57:11.000Z", "upvotes": 13}},
            {"paper": {"id": "2605.00001", "title": "Humanoid whole-body control", "summary": "new", "publishedAt": "2026-05-01T00:00:00.000Z",
                       "upvotes": 40, "ai_keywords": ["humanoid robot", "RL"]}},
        ])

    docs = asyncio.run(ml_papers.hf_papers(_client(handler), '"humanoid robot"', 5, min_year=2025))
    assert [d.title for d in docs] == ["Humanoid whole-body control"]
    d = docs[0]
    assert (d.url, d.published, d.source_type, d.extra["upvotes"]) == ("https://huggingface.co/papers/2605.00001", "2026-05-01", "preprint", 40)


def test_openreview():
    def handler(r):
        assert r.url.params["source"] == "forum"
        return httpx.Response(200, json={"notes": [
            {"id": "a1", "pdate": 1746644399247, "content": {"title": {"value": "Humanoid pose learning"}, "TLDR": {"value": "Learn from videos"},
                                                           "venue": {"value": "ICRA Workshop"}}},
            {"id": "a0", "cdate": 1546300800000, "content": {"title": {"value": "Old note"}}},
        ]})

    docs = asyncio.run(ml_papers.openreview(_client(handler), "humanoid robot", 5, min_year=2024))
    assert [d.url for d in docs] == ["https://openreview.net/forum?id=a1"]
    assert docs[0].published == "2025-05-07" and docs[0].snippet == "Learn from videos" and "ICRA Workshop" in docs[0].source_name
