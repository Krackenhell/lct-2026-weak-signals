"""Протоколы проверки гипотез П9–П17 и быстрых исправлений (вторая половина docs/research/ИССЛЕДОВАНИЕ_И_ГИПОТЕЗЫ.md), без сети."""
import asyncio
import json
import math
import time

import pytest
from fastapi.testclient import TestClient

from app import main as main_mod
from app.collectors.base import RawDoc
from app.config import get_settings
from app.db import SessionLocal
from app.llm import tasks
from app.ml.model import SignalModel
from app.models import Candidate, Run
from app.pipeline import emergence, runner
from app.pipeline.decide import decide
from app.pipeline.passport import evidence_checks, ladder, passport, pct_capped, robustness, topic_relation, why_early
from tests.fakes import FakeWeb
from tests.test_hypotheses import _cand
from tests.test_llm_tasks import ScriptedLLM, run

# ---------------------------------------------------------------- П9. Классификатор без бонуса «нет GitHub = сигнал»

SIGN = {"log_total_works": -1, "recent_share": 1, "growth": 1, "wiki_exists": -1, "log_wiki_views": -1, "share_science": 1,
        "specific_tech": 1, "mass_adoption": -1, "market_leaders": -1, "standard": -1, "hype": -1, "novelty": 1, "textbook": -1,
        "maturity": -1, "event": 1}


def test_production_model_has_no_github_and_no_inverted_signs():
    m = SignalModel.load()
    assert m and not {"log_gh_repos_12m", "log_hn_12m", "independent", "early_stage", "benefit"} & set(m.features)
    w = dict(zip(m.features, m.coef, strict=True))
    assert not [f for f, s in SIGN.items() if f in w and s * w[f] < -1e-6]  # знаки весов совпадают со смыслом признаков


def test_github_invariance():
    m = SignalModel.load()
    x = {f: mu for f, mu in zip(m.features, m.mean, strict=True)}
    assert m.predict({**x, "log_gh_repos_12m": 0.0, "log_hn_12m": 0.0}) == m.predict({**x, "log_gh_repos_12m": 8.0, "log_hn_12m": 5.0})


def test_rules_mode_keeps_previous_model():
    rules = SignalModel.load(get_settings().model_dir / "signal_model_rules.json")
    assert rules and "log_gh_repos_12m" in rules.features  # режим без Jev — прежняя модель


def test_slices_are_published():
    m = json.loads((get_settings().model_dir / "metrics.json").read_text(encoding="utf-8"))
    sl = m["slices"]["false_signal_share"]
    assert {"Хайп", "«Трудные» отрицательные", "Зрелые"} <= set(sl) and m["model_exclude"]["features"]


# ---------------------------------------------------------------- П17. YC — не раунд; лестница «почему рано»

def _items(*events):
    return [{"type": t, "event": e, "title": f"doc {i}", "url": f"https://site{i}.org/x", "date": f"202{3 + i % 3}-01-01"} for i, (t, e) in enumerate(events)]


def test_yc_startup_is_not_a_funding_round():
    items = _items(("startup", "startup"), ("preprint", None), ("preprint", None))
    ans = {f"doc_{i}": {"value": 0.9} for i in range(1, 4)}
    pp = passport(items, {**ans, "event": {"value": 0.0}}, 3)
    assert pp["event_level"] == 3 and not pp["hard_event"] and pp["startups"] == 1 and pp["funding_news"] == 0


def test_ladder_and_why_early():
    lad = ladder(_items(("preprint", None), ("community", None), ("grant", "grant")))
    by = {s["channel"]: s["n"] for s in lad}
    assert by == {"science": 1, "community": 1, "money": 1, "press": 0}
    text = why_early(lad, wiki=False)
    assert "Уже есть: наука" in text and "Ещё нет: пресса, энциклопедия" in text


# ---------------------------------------------------------------- П12. Фиксация плана

def test_plan_cache_second_call_does_not_ask_llm(tmp_path):
    llm = ScriptedLLM(json.dumps({"query_en": ["multilayer graphene"], "topic_en": "graphene", "subqueries": ["rhombohedral graphene"]}))
    p1, r1 = run(tasks.plan_query(llm, "многослойный графен", cache_dir=tmp_path))
    p2, r2 = run(tasks.plan_query(llm, "многослойный графен", cache_dir=tmp_path))
    assert len(llm.prompts) == 1 and r1 and r2 is None and p2["plan_cached"] and p1["subqueries"] == p2["subqueries"]
    run(tasks.plan_query(llm, "многослойный графен", cache_dir=tmp_path, refresh=True))  # replan — новый вызов
    assert len(llm.prompts) == 2


def test_plan_cache_misses_on_other_model_and_skips_lexicon(tmp_path):
    llm = ScriptedLLM(json.dumps({"subqueries": ["a b"]}))
    other = ScriptedLLM(json.dumps({"subqueries": ["a b"]}))
    other.model = "GigaChat-2"
    run(tasks.plan_query(llm, "x тема", cache_dir=tmp_path))
    run(tasks.plan_query(other, "x тема", cache_dir=tmp_path))
    assert len(other.prompts) == 1  # смена модели — промах кэша
    bad = ScriptedLLM("не JSON")
    run(tasks.plan_query(bad, "y тема", cache_dir=tmp_path))
    run(tasks.plan_query(bad, "y тема", cache_dir=tmp_path))
    assert len(bad.prompts) == 2  # словарный (неуспешный) план не кэшируется


def test_hn_window_is_rounded_to_day():
    import inspect

    from app.pipeline import discovery

    assert "// 86400" in inspect.getsource(discovery.build_corpus)


# ---------------------------------------------------------------- П14. Сравнение с объёмом темы

def test_subfield_exclusion_and_relation():
    rel = topic_relation({2022: 800, 2023: 900, 2024: 1000, 2025: 1200}, {2022: 3000, 2023: 3200, 2024: 3500, 2025: 3800}, 2026)
    assert rel["share"] > 0.25 and rel["works"] >= 1000
    a = {**_cand("droplet microfluidics"), "topic_rel": rel}
    assert decide([a], None, 15)[0]["code"] == "subfield"
    small = topic_relation({2024: 10, 2025: 30}, {2022: 3000, 2023: 3200, 2024: 3500, 2025: 3800}, 2026)
    assert small["faster"] > 1 and decide([{**_cand("x y"), "topic_rel": small}], None, 15)[0]["status"] == "signal"


# ---------------------------------------------------------------- П13. Импульс роста

def test_series_reconstruction_and_live_impulse():
    s = (40, 25, 10, 5)
    older, age = 3, 4.0
    f = {"log_works_total": math.log1p(sum(s) + older), "log_works_recent2": math.log1p(s[0] + s[1]),
         "growth2": math.log1p((s[0] + s[1]) / 2) - math.log1p((s[2] + s[3]) / 2),
         "accel": (math.log1p(s[0]) - math.log1p(s[1])) - (math.log1p(s[1]) - math.log1p(s[2])),
         "recent_share3": (s[0] + s[1] + s[2]) / (sum(s) + older), "age_years": age}
    rec = emergence.reconstruct_series(f)
    assert max(abs(a - b) for a, b in zip(rec[:4], s, strict=True)) < 1e-3
    hi = emergence.live_impulse({2022: 5, 2023: 10, 2024: 25, 2025: 40}, 2026, 3)
    assert hi["level"] == "high"
    assert emergence.live_impulse({2025: 2}, 2026, 1)["level"] is None  # нет научной истории — сигнал по событиям


def test_emergence_check_published():
    e = json.loads((get_settings().model_dir / "emergence.json").read_text(encoding="utf-8"))
    assert e["reconstruction_max_error"] < 1e-3 and "все индикаторы без отбора (заранее заданный вариант)" in e["variants"]


# ---------------------------------------------------------------- П15. Очередь и бюджет; П10 «только LLM»; П11 пул

def test_queue_info_and_budget(monkeypatch):
    from app.api.routes import queue_info

    with SessionLocal() as s:
        a = Run(query="q1", status="running")
        b = Run(query="q2", status="queued")
        c = Run(query="q3", status="queued")
        s.add_all([a, b, c])
        s.commit()
        q = queue_info(s, c)
        assert q["ahead"] >= 2 and q["eta_seconds"] > 0
        for r in (a, b, c):
            r.status = "failed"
        s.commit()


def test_run_budget_drops_unfinished_candidates(monkeypatch):
    monkeypatch.setenv("RUN_BUDGET_SECONDS", "1")
    get_settings.cache_clear()
    try:
        orig = runner.evidence_mod.gather

        async def slow(http, phrase, *a, **k):
            if "chiplet" not in phrase.lower():  # все, кроме одного кандидата, «зависают» дольше бюджета
                await asyncio.sleep(5)
            return await orig(http, phrase, *a, **k)

        monkeypatch.setattr(runner.evidence_mod, "gather", slow)
        monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
        with SessionLocal() as s:
            r = Run(query="edge AI бюджет", options={})
            s.add(r)
            s.commit()
            rid = r.id
        asyncio.run(runner.execute(rid))
        with SessionLocal() as s:
            r = s.get(Run, rid)
            assert r.status == "done", r.error
            assert r.stats["budget"]["checked"] < r.stats["budget"]["total"]
            assert r.stats["pool"] and r.plan["scope_en"]
    finally:
        get_settings.cache_clear()


def test_llm_only_mode_skips_corpus(monkeypatch):
    class OnlyNames(ScriptedLLM):
        async def complete(self, system, user, temperature=0.2, max_tokens=1500):
            self.prompts.append(user)
            from app.llm.providers import LLMResult
            text = '["NeuromorphicEventCameras", "edge inference accelerator"]' if "слабых сигналов" in user else ""
            return LLMResult(text, self.provider, self.model, 1, ok=bool(text))

    llm = OnlyNames("")
    web = FakeWeb()
    monkeypatch.setattr(runner, "HttpClient", web.client)
    monkeypatch.setattr(runner, "get_llm", lambda: llm)
    with SessionLocal() as s:
        r = Run(query="edge AI только LLM", options={"seed_candidates": True})
        s.add(r)
        s.commit()
        rid = r.id
    asyncio.run(runner.execute(rid))
    with SessionLocal() as s:
        r = s.get(Run, rid)
        cands = s.query(Candidate).filter_by(run_id=rid).all()
        assert r.status == "done" and r.stats["corpus_docs"] == 0
        assert cands and all(c.origin == "llm_baseline" for c in cands)
        assert "Neuromorphic Event Cameras" in {c.name for c in cands}  # слитное название разбито на слова


# ---------------------------------------------------------------- Быстрые исправления

def test_live_search_switch_and_daily_cap(monkeypatch):
    monkeypatch.setenv("LIVE_SEARCH", "false")
    get_settings.cache_clear()
    try:
        with TestClient(main_mod.app) as c:
            r = c.post("/api/search", json={"query": "совсем новая тема выключателя"})
            assert r.status_code == 503 and "Готовые результаты" in r.json()["detail"]
    finally:
        get_settings.cache_clear()


def test_no_100_percent_in_reasons_and_robustness():
    assert pct_capped(1.0) == "выше 95%" and pct_capped(0.0) == "ниже 5%"
    a = _cand("some standard protocol")
    a["res"].answers["standard"] = {"value": 1.0}
    d = decide([a], None, 15)[0]
    assert d["code"] == "standard" and "100%" not in d["reason"]
    rb = robustness(0.99999, [{"feature": "g", "label": "Рост", "contribution": 9.0}], intercept=5.0)
    assert "100%" not in rb["text"]


def test_evidence_checks_unchanged_for_yc_only():
    pp = passport(_items(("startup", "startup")), {"doc_1": {"value": 0.9}}, 1)
    assert evidence_checks(pp)["items"][3]["ok"] is True  # уровень гранта засчитывается как событие, но не «твёрдое»


def test_snapshot_redecide_reproduces_statuses(tmp_path):
    from app.ml.bench import redecide, save_snapshot

    assessed = [_cand(n, p) for n, p in (("droplet sorting", 0.9), ("perovskite tandems", 0.8), ("weak thing", 0.3))]
    for a in assessed:
        a["ev"].docs = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"t{i}", source_name="arXiv", source_type="preprint", collector="arxiv") for i in range(5)]
        a["prob"] = a["prob"]
    live = decide(assessed, None, 15)
    p = save_snapshot(tmp_path / "s.json.gz", 1, "q", {"topic_en": "t"}, [], assessed, {"topic_terms": [], "anchors": frozenset(), "crowding": True})
    t0 = time.time()
    rows = redecide(p, model_path=tmp_path / "нет-модели.json")
    assert [r["status"] for r in rows] == [d["status"] for d in live] and time.time() - t0 < 5


@pytest.mark.parametrize("q", ["перспективные решения в финтехе"])
def test_bench_queries_file(q):
    from app.ml.bench import QUERIES

    assert q in QUERIES["regression"] and not set(QUERIES["holdout"]) & set(QUERIES["dev"])
