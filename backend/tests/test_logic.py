"""Тесты детерминированной логики: без сети и без ключей моделей."""
import asyncio
import math

from app.collectors.base import RawDoc
from app.decision.base import DecisionResult
from app.decision.heuristic import HeuristicDecision
from app.llm.providers import parse_json
from app.ml.model import SignalModel
from app.pipeline import discovery
from app.pipeline.decide import decide
from app.pipeline.evidence import Evidence, _dedupe
from app.pipeline.features import FEATURES, numeric_features
from app.pipeline.questions import QUESTIONS, build_state
from app.pipeline.trust import classify


def doc(**kw) -> RawDoc:
    base = dict(url="https://example.com/a", title="T", source_type="news", collector="x")
    return RawDoc(**{**base, **kw})


def test_trust_levels():
    assert classify(doc(source_type="science"))[1] == "high"
    assert classify(doc(source_type="preprint"))[1] == "medium"
    assert classify(doc(url="https://www.prnewswire.com/news/x"))[0] == "press"
    assert classify(doc(url="https://medium.com/@a/b"))[1] == "low"
    assert classify(doc(url="https://www.reuters.com/tech/x"))[1] == "high"


def test_arxiv_versions_are_one_document():
    docs = [doc(url="https://arxiv.org/abs/2609.1v1", title="A"), doc(url="https://arxiv.org/abs/2609.1v2", title="A2"), doc(url="https://arxiv.org/abs/2609.2v1", title="B")]
    assert len(_dedupe(docs)) == 2


def test_numeric_features_young_vs_mature():
    young = Evidence("x", yearly={2025: 10, 2026: 40}, wiki={"exists": False}, today="2026-09-23")
    old = Evidence("y", yearly={y: 500 for y in range(1995, 2027)}, wiki={"exists": True, "monthly_views": 30000}, today="2026-09-23")
    fy, fo = numeric_features(young), numeric_features(old)
    assert fy["recent_share"] == 1.0 and fy["age_years"] == 1.0
    assert fo["age_years"] == 31.0 and fo["wiki_exists"] == 1.0
    assert fy["growth"] > fo["growth"]


def test_merge_synonyms_and_generic():
    merged = discovery.merge([
        {"name_en": "Tokenized deposits", "doc_idx": [1]},
        {"name_en": "tokenized deposit", "doc_idx": [2]},
        {"name_en": "machine learning", "doc_idx": [3]},
    ])
    assert len(merged) == 1 and merged[0]["doc_idx"] == [1, 2] and merged[0]["support"] == 2


def test_mine_phrases_needs_two_documents():
    docs = [doc(title="Optical circuit switching for AI clusters", language="en"), doc(title="Scaling optical circuit switching networks", language="en"), doc(title="Unrelated topic here", language="en")]
    names = [c["name_en"].lower() for c in discovery.mine_phrases(docs)]
    assert any("optical circuit switching" in n for n in names)


def test_parse_json_from_markdown():
    assert parse_json('Ответ:\n```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json("[1, 2]") == [1, 2]
    assert parse_json("нет json") is None


def test_heuristic_decision_answers_all_questions():
    state = build_state("agent payments protocol", "fintech", [{"type": "preprint", "source": "arXiv", "date": "2026-09-01", "title": "We propose a novel prototype", "snippet": "pilot"}])
    res = asyncio.run(HeuristicDecision().ask(state, QUESTIONS))
    assert set(res.answers) == set(QUESTIONS)
    assert all(0 <= a["value"] <= 1 for a in res.answers.values())


def _assessed(name, answers, feats, prob, n_docs=5):
    ev = Evidence(name, docs=[doc(url=f"https://arxiv.org/abs/{i}", source_type="preprint") for i in range(n_docs)])
    res = DecisionResult({k: {"type": "noul", "value": v} for k, v in answers.items()}, "test", "t", 0)
    return {"c": {"name_en": name}, "ev": ev, "items": [], "res": res, "features": feats, "prob": prob}


def test_decide_filters_and_ranking():
    model = SignalModel(features=list(FEATURES), mean=[0.0] * len(FEATURES), scale=[1.0] * len(FEATURES), coef=[0.1] * len(FEATURES), intercept=0.0, meta={})
    base = {"relevance": 0.9, "specific_tech": 0.9, "standard": 0.1, "mass_adoption": 0.1, "market_leaders": 0.1, "hype": 0.1}
    items = [
        _assessed("good", base, {}, 0.9),
        _assessed("standard", {**base, "standard": 0.8}, {}, 0.9),
        _assessed("mature", base, {"log_total_works": math.log1p(50000)}, 0.9),
        _assessed("offtopic", {**base, "relevance": 0.1}, {}, 0.9),
        _assessed("thin", base, {}, 0.9, n_docs=1),
        _assessed("unlikely", base, {}, 0.2),
    ]
    out = decide(items, model, top_k=15)
    status = {a["c"]["name_en"]: (d["status"], d.get("code")) for a, d in zip(items, out)}
    assert status["good"] == ("signal", None)
    assert status["standard"][1] == "standard"
    assert status["mature"][1] == "mature"
    assert status["offtopic"][1] == "irrelevant"
    assert status["thin"][1] == "low_evidence"
    assert status["unlikely"][1] == "low_probability"
