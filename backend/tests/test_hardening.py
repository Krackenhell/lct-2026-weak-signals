"""Устойчивость и безопасность: выход за пределы каталога сайта, кривые ответы LLM, повреждённый кэш, очередь запусков."""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.collectors.http import HttpClient, prune_cache
from app.db import SessionLocal
from app.llm.tasks import extract_candidates, write_dossier
from app.models import Run
from app.pipeline import runner
from tests.fakes import FakeWeb
from tests.test_llm_tasks import ScriptedLLM


def test_static_files_do_not_escape_dist(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>INDEX", encoding="utf-8")
    (dist / "logo.svg").write_text("<svg/>", encoding="utf-8")
    (tmp_path / ".env").write_text("GIGACHAT_AUTH_KEY=secret", encoding="utf-8")
    monkeypatch.setattr(main_mod, "_DIST", dist)
    c = TestClient(main_mod.app)
    for path in ("/..%2F.env", "/%2E%2E/.env", "/..%2F..%2F..%2Fetc%2Fpasswd"):
        r = c.get(path)
        assert "secret" not in r.text and "root:" not in r.text, path
    assert c.get("/logo.svg").text == "<svg/>"
    assert "INDEX" in c.get("/runs/5").text  # маршруты интерфейса отдают index.html


def test_extract_candidates_tolerates_odd_docs_field():
    llm = ScriptedLLM(json.dumps([
        {"name_en": "tokenized deposits", "docs": None},
        {"name_en": "agentic payments", "docs": 1},
        {"name_en": "zk KYC", "docs": "0, 1, 9"},
        {"name_en": "x402", "docs": [0, "1", -3, 99]},
    ]))
    out, _ = asyncio.run(extract_candidates(llm, "fintech", [{"title": "a"}, {"title": "b"}]))
    assert [c["doc_idx"] for c in out] == [[], [1], [0, 1], [0, 1]]


def test_dossier_fields_are_strings():
    llm = ScriptedLLM(json.dumps({"description": ["Первое.", "Второе."], "advantage": None, "risks": {"a": 1}, "name_ru": "токенизация"}))
    data, _ = asyncio.run(write_dossier(llm, "финтех", "tokenization", [], ["факт"]))
    assert data["description"] == "Первое. Второе." and data["advantage"] == "" and isinstance(data["risks"], str)


def test_corrupted_cache_file_is_refetched(tmp_path, monkeypatch):
    monkeypatch.setenv("CACHE_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    try:
        calls = []

        def handler(request):
            calls.append(request.url)
            return httpx.Response(200, json={"ok": 1})

        async def go():
            http = HttpClient()
            http._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            assert await http.get("https://example.org/a") == {"ok": 1}
            path = http._cache_path("https://example.org/a", None)
            path.write_text('{"ok": ', encoding="utf-8")  # файл, записанный наполовину
            assert await http.get("https://example.org/a") == {"ok": 1}
            await http.close()

        asyncio.run(go())
        assert len(calls) == 2
        assert not list(tmp_path.glob("*.tmp"))
        for p in tmp_path.glob("*.json"):  # файл записан только что: «состариваем», иначе сравнение времени зависит от точности часов
            os.utime(p, (p.stat().st_mtime - 10, p.stat().st_mtime - 10))
        assert prune_cache(tmp_path, 0) >= 1  # просроченные файлы удаляются
    finally:
        get_settings.cache_clear()


def _new_run(query: str) -> int:
    with SessionLocal() as s:
        r = Run(query=query, options={})
        s.add(r)
        s.commit()
        return r.id


def test_runs_wait_in_queue_and_one_failing_candidate_does_not_fail_run(monkeypatch):
    monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
    active, peak = 0, 0
    real = runner._execute

    async def counted(ctx, s):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        try:
            return await real(ctx, s)
        finally:
            active -= 1

    monkeypatch.setattr(runner, "_execute", counted)
    gather = runner.evidence_mod.gather
    first = []

    async def flaky(http, name, *a, **kw):
        if not first:
            first.append(name)
            raise RuntimeError("неожиданный ответ источника")
        return await gather(http, name, *a, **kw)

    monkeypatch.setattr(runner.evidence_mod, "gather", flaky)
    ids = [_new_run(q) for q in ("edge AI", "робототехника", "финтех", "индустриальный ИИ")]

    async def all_runs():
        await asyncio.gather(*(runner.execute(i) for i in ids))

    asyncio.run(all_runs())
    assert peak <= 2  # MAX_PARALLEL_RUNS по умолчанию
    with SessionLocal() as s:
        runs = [s.get(Run, i) for i in ids]
        assert all(r.status == "done" for r in runs), [(r.query, r.error) for r in runs]
        assert sum((r.stats or {}).get("candidate_errors", 0) for r in runs) == 1


def test_repeat_query_opens_recent_result_instantly(monkeypatch):
    from app.api import routes

    started = []

    async def fake_execute(run_id):
        started.append(run_id)

    monkeypatch.setattr(routes.runner, "execute", fake_execute)
    prov = {"llm": "none:template", "pipeline": runner.PIPELINE_VERSION}
    with SessionLocal() as s:
        done = Run(query="Квантовые  сенсоры!", status="done", stats={"signals": 3}, providers=prov, options={})
        old = Run(query="микрофлюидика", status="done", stats={"signals": 2}, providers=prov, options={},
                  created_at=datetime.now(timezone.utc) - timedelta(days=5))
        s.add_all([done, old])
        s.commit()
        done_id = done.id
    with TestClient(main_mod.app) as c:
        r = c.post("/api/search", json={"query": "квантовый сенсор"}).json()  # другая словоформа — та же тема
        assert r["id"] == done_id and r["reused"] is True and not started
        r = c.post("/api/search", json={"query": "квантовые сенсоры", "fresh": True}).json()
        assert r["id"] != done_id and "reused" not in r and started == [r["id"]]
        assert c.post("/api/search", json={"query": "микрофлюидика"}).json().get("reused") is None  # старше REUSE_HOURS — пересчёт
        r2 = c.post("/api/search", json={"query": "квантовые сенсоры"}).json()
        assert r2["id"] == r["id"] and r2["status"] == "queued"  # тот же запрос уже в работе — второй не запускается
        assert len(started) == 2


@pytest.mark.parametrize("a, b, same", [
    ("технология многослойного графена", "технологии многослойного графена", True),
    ("микрофлюидные чипы", "Микрофлюидный чип", True),
    ("органы на чипе", "органы-на-чипе", True),
    ("технологии в финтехе", "решения в финтехе", False),
    ("безопасность ИИ", "ИИ для безопасности", False),
    ("графен", "графит", False),
    ("квантовые сенсоры", "квантовые компьютеры", False),
])
def test_query_key_matches_word_forms_only(a, b, same):
    from app.api.routes import _norm_query

    assert (_norm_query(a) == _norm_query(b)) is same


@pytest.mark.parametrize("change, blocked", [
    ({}, False),
    ({"providers": {"llm": "none:template", "pipeline": "старая"}}, True),  # другая версия конвейера
    ({"stats": {"signals": 3, "candidates": 30, "decision_fallback": 10}}, True),  # decision-модель не ответила по трети
    ({"stats": {"signals": 3, "degraded": True}}, True),  # OpenAlex был недоступен
    ({"stats": {"signals": 0}}, True),
])
def test_reuse_gates(change, blocked):
    from app.api.routes import reuse_blockers

    base = {"query": "x", "status": "done", "stats": {"signals": 3, "candidates": 30},
            "providers": {"llm": "none:template", "pipeline": runner.PIPELINE_VERSION}, "plan": {"generated_by": "lexicon"}}
    assert bool(reuse_blockers(Run(**{**base, **change}))) is blocked


def test_precompute_runs_topics_once(monkeypatch):
    from app import precompute

    monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
    first = asyncio.run(precompute.refresh_once(["edge AI предрасчёт", "робототехника предрасчёт"]))
    assert len(first) == 2
    with SessionLocal() as s:
        assert all(s.get(Run, i).status == "done" for i in first)
    assert asyncio.run(precompute.refresh_once(["edge AI предрасчёт", "робототехника предрасчёт"])) == []  # свежие — не пересчитываются


def test_cost_of_request_in_rubles(monkeypatch):
    from app.config import get_settings
    from app.llm.providers import OpenAICompatible
    from app.pipeline import cost

    usage = {"gigachat": {"model": "GigaChat-2-Max", "calls": 20, "tokens": 50_000}, "jev": {"model": "jev-latest", "calls": 30, "tokens": 0}}
    c = cost.estimate(usage)
    assert c["total_rub"] == 32.5 and {x["provider"] for x in c["lines"]} == {"gigachat", "jev"}  # 50 тыс. токенов × 0,65 ₽ (тариф Max, 19.10)
    monkeypatch.setenv("DECISION_RUB_PER_CALL", "0.5")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://ollama:11434/v1")
    get_settings.cache_clear()
    try:
        c = cost.estimate({"openai": {"model": "qwen3:8b", "calls": 5, "tokens": 9000}, "jev": {"model": "jev-latest", "calls": 30, "tokens": 0}})
        assert c["total_rub"] == 15.0  # локальная LLM бесплатна, Jev — 30 × 0,5 ₽
    finally:
        get_settings.cache_clear()

    async def fake_post(*a, **kw):
        req = httpx.Request("POST", "http://x")
        return httpx.Response(200, request=req, json={"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 7, "completion_tokens": 3}})

    llm = OpenAICompatible()
    monkeypatch.setattr(llm._client, "post", fake_post)
    res = asyncio.run(llm.complete("s", "u"))
    assert res.text == "ok" and res.usage == {"prompt": 7, "completion": 3, "total": 10}


def test_paper_titles_and_crowded_themes_do_not_fill_top():
    from types import SimpleNamespace

    from app.collectors.base import RawDoc
    from app.pipeline.decide import decide
    from app.pipeline.discovery import clean_name, merge

    assert clean_name("solid state battery development") == "solid state battery"
    assert clean_name("Development of solid-state batteries") == "solid-state batteries"
    assert merge([{"name_en": "Dendrimer applications", "doc_idx": [0]}])[0]["name_en"] == "Dendrimer"

    def cand(name, p=0.9):
        answers = {k: {"value": v} for k, v in {"relevance": 0.9, "specific_tech": 0.9, "is_technology": 0.9}.items()}
        ev = SimpleNamespace(docs=[RawDoc(url=f"https://arxiv.org/abs/{i}", title="t", source_name="arXiv", source_type="preprint", collector="arxiv")
                                   for i in range(4)])
        return {"c": {"name_en": name}, "res": SimpleNamespace(ok=True, answers=answers), "features": {}, "prob": p, "ev": ev,
                "passport": {"level": "B"}}

    names = ["Annealing-based Quantum Neural Networks", "Quantum Kernel SVM", "Variational Quantum Algorithms", "Quantum NLP",
             "optical interconnect", "Stackelberg Model of AI Security", "CXL memory pooling"]
    out = decide([cand(n, 0.99 - i / 100) for i, n in enumerate(names)], None, 15)
    status = {n: (d["status"], d.get("code")) for n, d in zip(names, out, strict=True)}
    assert status["Quantum NLP"] == ("excluded", "crowded")
    assert status["Stackelberg Model of AI Security"] == ("excluded", "paper_title")
    assert sum(1 for s, _ in status.values() if s == "signal") == 5


def test_link_check_skips_internal_addresses():
    from app.pipeline import links

    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "evil.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1:8000/api/runs"})
        return httpx.Response(200)

    redirect = asyncio.run(links.check_all(["https://evil.example/r"], transport=httpx.MockTransport(handler)))
    assert redirect == {"https://evil.example/r": "restricted"} and seen == ["https://evil.example/r"]
    seen.clear()
    urls = ["http://127.0.0.1:8000/api/runs", "http://10.0.0.5/admin", "http://localhost/x", "http://[::1]/", "http://169.254.169.254/latest/meta-data",
            "https://arxiv.org/abs/1"]
    res = asyncio.run(links.check_all(urls, transport=httpx.MockTransport(handler)))
    assert res["https://arxiv.org/abs/1"] == "ok" and seen == ["https://arxiv.org/abs/1"]
    assert all(res[u] == "restricted" for u in urls[:-1])


def test_webhook_dns_rebinding_is_blocked():
    """Имя, которое разрешается во внутренний адрес, не проходит (раньше проверялась только запись адреса в URL)."""
    import asyncio

    from app.pipeline.links import resolves_internal

    assert asyncio.run(resolves_internal("https://localhost/hook"))
    assert asyncio.run(resolves_internal("https://127.0.0.1.nip.invalid/hook"))  # не разрешается — небезопасно


def test_grouped_cv_groups_synonyms():
    from app.ml.grouped_cv import synonym_groups

    rows = [{"phrase": "solid-state battery"}, {"phrase": "all solid state batteries"}, {"phrase": "vector database"}]
    g = synonym_groups(rows)
    assert g[0] == g[1] != g[2]
