"""Устойчивость и безопасность: выход за пределы каталога сайта, кривые ответы LLM, повреждённый кэш, очередь запусков."""
import asyncio
import json

import httpx
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
