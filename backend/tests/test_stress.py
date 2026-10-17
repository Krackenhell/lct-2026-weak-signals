"""Стресс-тест: параллельные запросы, необычный ввод, отказы источников и моделей.

Сеть поддельная, поэтому тест проверяет устойчивость кода (гонки в БД, обработку ошибок),
а не пропускную способность внешних API.
"""
import asyncio
import time

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.decision.base import DecisionResult
from app.llm.tasks import rule_check_query
from app.main import app
from app.models import Candidate, Run
from app.pipeline import runner
from tests.fakes import FakeWeb


def _new_run(query: str, **options) -> int:
    with SessionLocal() as s:
        r = Run(query=query, options=options)
        s.add(r)
        s.commit()
        return r.id


def test_ten_parallel_runs_finish_without_errors(monkeypatch):
    monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
    queries = ["edge AI", "робототехника", "перспективные решения в финтехе", "инфраструктура для ИИ", "индустриальный ИИ",
               "кибербезопасность ИИ", "квантовые вычисления", "энергетика и накопители", "Привет", "медицинские технологии"]
    ids = [_new_run(q) for q in queries]

    async def all_runs():
        await asyncio.gather(*(runner.execute(i) for i in ids))

    t = time.perf_counter()
    asyncio.run(all_runs())
    elapsed = time.perf_counter() - t
    with SessionLocal() as s:
        runs = [s.get(Run, i) for i in ids]
        statuses = {r.query: r.status for r in runs}
        assert statuses.pop("Привет") == "rejected"
        assert set(statuses.values()) == {"done"}, [(r.query, r.error) for r in runs if r.status == "failed"]
        for r in runs:
            if r.status == "done":
                n = s.query(Candidate).filter_by(run_id=r.id, status="signal").count()
                assert n == r.stats["signals"] and n <= 15
                assert r.stats["timing"] and sum(r.stats["timing"].values()) > 0
    assert elapsed < 120  # без сетевых задержек 10 параллельных запросов укладываются в секунды


@pytest.mark.parametrize("query, ok", [
    ("а" * 300, False),  # 300 одинаковых букв — не направление
    ("SELECT * FROM runs; DROP TABLE runs;--", False),
    ("<script>alert(1)</script>", False),
    ("🚀🚀🚀", False),
    ("12345", False),
    ("edge AI 🚀", True),
    ("Machine unlearning for banks", True),
    ("финтех; DROP TABLE runs", True),  # технологический запрос с мусором: принимается, но мусор не исполняется
])
def test_unusual_input(query, ok):
    assert rule_check_query(query)["ok"] is ok, query


def test_injection_strings_are_stored_as_text(monkeypatch):
    with TestClient(app) as c:
        for q in ["финтех; DROP TABLE runs", "<script>alert(1)</script>"]:
            r = c.post("/api/search", json={"query": q})
            assert r.status_code == 200
            got = c.get(f"/api/runs/{r.json()['id']}").json()
            assert got["query"] == q  # строка сохранена как есть, таблицы целы
        assert c.get("/api/runs").status_code == 200


def test_all_sources_down_gives_empty_but_honest_result(monkeypatch):
    from app.collectors import http as http_mod

    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    down = {"export.arxiv.org", "api.openalex.org", "hn.algolia.com", "api.github.com", "en.wikipedia.org", "api.gdeltproject.org",
            "habr.com", "api.crossref.org", "cyberleninka.ru", "www.ebi.ac.uk", "siliconangle.com", "techcrunch.com", "www.theblock.co", "www.prnewswire.com", "vc.ru", "www.cnews.ru",
            "www.finextra.com", "technode.com", "pandaily.com", "www.scmp.com", "www.36kr.com", "www.ithome.com", "www.cnbeta.com.tw",
            "www.infoq.cn", "api.reporter.nih.gov", "api.nsf.gov", "gtr.ukri.org", "yc-oss.github.io", "huggingface.co", "api2.openreview.net"}
    monkeypatch.setattr(runner, "HttpClient", FakeWeb(down=down).client)
    rid = _new_run("робототехника")
    asyncio.run(runner.execute(rid))
    with SessionLocal() as s:
        run = s.get(Run, rid)
        assert run.status == "done" and run.stats["signals"] == 0  # не падает и не выдумывает сигналы
        assert all(v["ok"] == 0 for v in run.stats["http"].values())


class DownJev:
    provider, model = "jev", "jev-latest"

    async def ask(self, state, questions):
        return DecisionResult({}, "jev", "jev-latest", 0, ok=False, error="ReadTimeout")


def test_decision_model_outage_falls_back_to_rules(monkeypatch):
    monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
    monkeypatch.setattr(runner, "get_decision_model", lambda: DownJev())
    rid = _new_run("edge AI")
    asyncio.run(runner.execute(rid))
    with SessionLocal() as s:
        run = s.get(Run, rid)
        cands = s.query(Candidate).filter_by(run_id=rid).all()
        assert run.status == "done" and run.stats["decision_fallback"] == len(cands) > 0
        assert run.stats["signals"] > 0  # выдача не пустая из-за сбоя одной модели
        assert all(c.contributions["passport"].get("fallback") for c in cands)
        assert not any(c.exclusion_code == "no_decision" for c in cands)


def test_crash_inside_pipeline_is_recorded_not_hanging(monkeypatch):
    def broken():
        raise RuntimeError("сломался источник")

    monkeypatch.setattr(runner, "HttpClient", broken)
    rid = _new_run("edge AI")
    asyncio.run(runner.execute(rid))
    with SessionLocal() as s:
        run = s.get(Run, rid)
        assert run.status == "failed" and "сломался источник" in run.error and run.finished_at is not None
