"""Честность обучения и оценки (этап 1): на синтетических данных, без сети, с записью модели во временную папку."""
import asyncio
import json
import random

import pytest

from app.config import get_settings
from app.ml import train
from app.ml.model import SignalModel
from app.pipeline.features import ANSWERS, NUMERIC

DOMAINS = ["Финтех", "Роботы", "Edge"]

_ORIG_BOOT, _ORIG_REP = train._bootstrap_ci, train._repeated


@pytest.fixture(autouse=True, scope="module")
def faster_evaluation():
    # Логика оценки не зависит от числа повторов; в тестах 100 бутстрэп-выборок и 3 повтора вместо 1000 и 10,
    # иначе под замером покрытия каждый тест обучения шёл бы десятки секунд.
    mp = pytest.MonkeyPatch()
    mp.setattr(train, "_bootstrap_ci", lambda y, p, n_boot=1000, seed=7: _ORIG_BOOT(y, p, min(n_boot, 100), seed))
    mp.setattr(train, "_repeated", lambda X, y, repeats=10: _ORIG_REP(X, y, 3))
    yield
    mp.undo()


def _row(i: int, label: int, n_docs: int, rng: random.Random) -> dict:
    sig = 1.0 if label else -1.0
    numeric = {f: rng.gauss(0, 1) for f in NUMERIC}
    numeric["growth"] = sig * 1.5 + rng.gauss(0, 0.7)  # единственный информативный признак
    numeric["log_total_works"] = abs(numeric["log_total_works"]) + 0.5 if n_docs else 0.0  # без доказательств — нет научной истории
    answers = {f: rng.random() for f in ANSWERS if f != "event"}  # «event» — как до переопроса: ответа нет
    return {"key": f"k{i}", "label": label, "name": f"tech {i}", "domain": DOMAINS[i % 3], "code": "signal" if label else "mature",
            "numeric": numeric, "answers": answers, "n_docs": n_docs}


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("model")
    mp = pytest.MonkeyPatch()
    mp.setattr(get_settings(), "model_dir", tmp)
    try:
        rng = random.Random(0)
        rows = [_row(i, i % 2, 5, rng) for i in range(90)]
        rows += [_row(100 + i, 1, 0, rng) for i in range(15)]  # сигналы без единого документа
        yield train.evaluate_and_fit(rows, "test:provider"), tmp
    finally:
        mp.undo()


def test_rows_without_evidence_are_not_used(report):
    rep, _ = report
    assert rep["n"] == 90 and rep["dropped_no_evidence"] == {"pos": 15, "neg": 0}
    assert rep["reference_all_rows"]["n"] == 105  # прежний способ показан отдельно — для сравнения


def test_intervals_and_repeats_are_reported(report):
    rep, _ = report
    lo, hi = rep["cv5_ci95"]["f1"]
    assert 0 <= lo <= rep["cv5"]["f1"] <= hi <= 1
    assert rep["cv5_repeated"]["repeats"] >= 3 and rep["cv5_repeated"]["f1_std"] >= 0
    for d in DOMAINS:
        v = rep["leave_one_domain_out"][d]
        assert v["n"] == 30 and v["n_pos"] >= train.MIN_LODO_POS and len(v["f1_ci95"]) == 2


def test_perfect_domain_reports_error_bound_not_100(report):
    rep, _ = report
    for v in rep["leave_one_domain_out"].values():
        if v.get("errors") == 0:
            assert 0 < v["error_rate_upper95"] < 0.2  # «без ошибок на N примерах; ошибок не больше X%»
    assert round(1 - 0.05 ** (1 / 33), 3) == 0.087


def test_lodo_with_few_signals_publishes_no_number(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_dir", tmp_path)
    rng = random.Random(3)
    rows = [_row(i, i % 2, 5, rng) for i in range(60)]
    rows += [{**_row(200 + i, int(i < 2), 5, rng), "domain": "Редкая"} for i in range(12)]  # всего 2 сигнала в области
    rep = train.evaluate_and_fit(rows, "test")
    assert rep["leave_one_domain_out"]["Редкая"] == {"too_few": True, "n": 12, "n_pos": 2}


def test_constant_feature_is_dropped_and_model_is_consistent(report):
    rep, out = report
    assert "event" in rep["features_dropped"] and "event" not in rep["features_used"]
    model = SignalModel.load(out / "signal_model.json")
    assert model.features == rep["features_used"] and len(model.coef) == len(model.features)
    assert model.meta["trained_on"] == 90 and model.meta["min_docs"] == train.MIN_DOCS
    # Информативный признак получил самый большой вес — модель учится тому, что есть в данных.
    top = max(rep["weights"], key=lambda w: abs(w["weight"]))
    assert top["feature"] == "growth" and top["weight"] > 0


def test_limitations_are_published(report):
    rep, _ = report
    assert any("Отрицательные примеры" in s for s in rep["limitations"])
    assert any(train.EVIDENCE_RULE in s for s in rep["limitations"]) and rep["evidence_rule"] == train.EVIDENCE_RULE


def test_model_predicts_with_missing_features():
    # Новый признак, которого не было при обучении, и пропущенный признак не ломают предсказание.
    m = json.loads((get_settings().model_dir / "signal_model.json").read_text(encoding="utf-8"))
    model = SignalModel(m["features"], m["mean"], m["scale"], m["coef"], m["intercept"], m.get("meta", {}))
    p = model.predict({"growth": 1.0, "event": 0.9})
    assert 0 < p < 1


def test_collect_uses_same_evidence_code_as_live_search(monkeypatch):
    from tests.fakes import FakeWeb

    monkeypatch.setattr(train, "HttpClient", FakeWeb().client)
    rows = [{"key": "a", "label": 1, "phrase": "Neuromorphic event cameras", "alt_terms": []},
            {"key": "b", "label": 0, "phrase": "Spiking photonic processors", "alt_terms": ["Chiplet interconnect fabrics"]}]
    out, store = asyncio.run(train.collect(rows))
    a, b = out
    assert a["n_docs"] > 0 and a["numeric"]["log_total_works"] > 0 and store["a"]
    # Нет находок по основной фразе — берётся запасной термин (как в живом поиске).
    assert b["phrase_used"] == "Chiplet interconnect fabrics" and b["n_docs"] > 0


def test_collect_retries_and_marks_incomplete_when_core_source_is_down(monkeypatch):
    from tests.fakes import FakeWeb

    async def no_sleep(_):
        return None

    monkeypatch.setattr(asyncio, "sleep", no_sleep)
    web = FakeWeb(down={"export.arxiv.org"})
    monkeypatch.setattr(train, "HttpClient", web.client)
    rows = [{"key": "a", "label": 1, "phrase": "Neuromorphic event cameras", "alt_terms": []}]
    out, _ = asyncio.run(train.collect(rows))
    assert out[0]["incomplete"] == ["arxiv"]  # признаки без препринтов неполные — пример помечен
    assert web.calls.count("export.arxiv.org") >= 4 * 5  # 4 попытки примера × 5 терпеливых повторов источника


def test_incomplete_rows_are_not_used_for_training(report):
    rng = random.Random(2)
    rows = [_row(i, i % 2, 5, rng) for i in range(60)] + [{**_row(99, 1, 5, rng), "incomplete": ["arxiv"], "name": "без arXiv"}]
    mp = pytest.MonkeyPatch()
    mp.setattr(get_settings(), "model_dir", report[1])
    try:
        rep = train.evaluate_and_fit(rows, "test")
    finally:
        mp.undo()
    assert rep["n"] == 60 and rep["incomplete_sources"] == {"rows": 1, "names": ["без arXiv"]}


def test_patient_client_waits_instead_of_skipping(monkeypatch):
    import httpx

    from app.collectors import http as http_mod
    from tests.fakes import FakeWeb

    sleeps = []

    async def fake_sleep(s):
        sleeps.append(s)

    monkeypatch.setattr(http_mod.asyncio, "sleep", fake_sleep)
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(429, headers={"retry-after": "60"}) if len(calls) < 3 else httpx.Response(200, json={"ok": 1})

    h = FakeWeb().client(patient=True)
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    assert asyncio.run(h.get("https://export.arxiv.org/api/query", cache=False)) == {"ok": 1}
    assert sleeps == [60.0, 60.0]  # в пакетной задаче ждём столько, сколько просит источник


def test_reask_sends_event_question_to_decision_model(monkeypatch):
    from app.decision.base import DecisionResult

    seen = {}

    class FakeJev:
        provider, model = "jev", "jev-test"

        async def ask(self, state, questions):
            seen["q"] = set(questions)
            return DecisionResult({"event": {"type": "score", "value": 4 / 6}, "novelty": {"type": "noul", "value": 0.7}}, "jev", "jev-test", 1)

    monkeypatch.setattr(train, "get_decision_model", lambda provider=None: FakeJev())
    rows = [{"key": "a", "phrase": "x"}]
    assert asyncio.run(train.ask_all(rows, {"a": []})) == "jev:jev-test"
    assert "event" in seen["q"] and "novelty" in seen["q"]
    assert rows[0]["answers"]["event"] == pytest.approx(4 / 6) and rows[0]["decision_ok"]


def test_refit_cli_keeps_original_metrics(tmp_path, monkeypatch):
    rng = random.Random(1)
    rows = [{**_row(i, i % 2, 5, rng), "provider": "jev:jev-latest"} for i in range(60)]
    (tmp_path / "training_rows.json").write_text(json.dumps(rows), encoding="utf-8")
    (tmp_path / "training_evidence.json").write_text("{}", encoding="utf-8")
    (tmp_path / "metrics.json").write_text(json.dumps({"cv5": {"f1": 0.946}}), encoding="utf-8")
    monkeypatch.setattr(get_settings(), "model_dir", tmp_path)
    monkeypatch.setattr("sys.argv", ["train", "--refit"])
    train.main()
    assert json.loads((tmp_path / "metrics_before.json").read_text(encoding="utf-8"))["cv5"]["f1"] == 0.946
    new = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    assert new["provider"] == "jev:jev-latest" and new["n"] == 60 and (tmp_path / "signal_model.json").exists()


def test_hard_negatives_are_in_the_seed():
    items = json.loads((get_settings().seed_dir / "negatives.json").read_text(encoding="utf-8"))["items"]
    hard = [i for i in items if i.get("hard")]
    assert len(hard) >= 20
    assert {i["code"] for i in hard} >= {"mature", "hype", "broad"}
    assert all(i["terms"] and i["domain"] for i in hard)
