"""Скрипт живой оценки (этап 2): прогоны по областям датасета и контрольные бессмысленные запросы."""
import argparse
import asyncio
import json

from app.config import get_settings
from app.ml import eval_live
from app.pipeline import runner
from tests.fakes import FakeWeb


def test_matching_with_dataset_terms():
    assert eval_live.matches("Tokenized deposits", ["tokenized deposit"])  # единственное/множественное число
    assert eval_live.matches("zero-knowledge KYC", ["zero knowledge KYC"])  # дефис не мешает
    assert not eval_live.matches("quantum sensing", ["tokenized deposits"])
    assert not eval_live.matches("AI", ["AI agents payments protocol"])  # одно общее слово — не совпадение


def test_fresh_report_with_nonsense_and_domain(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "model_dir", tmp_path)
    monkeypatch.setattr(runner, "HttpClient", FakeWeb().client)
    (tmp_path / "live_eval.json").write_text(json.dumps({"runs": [{"query": "старый прогон"}]}), encoding="utf-8")
    args = argparse.Namespace(only_discovery=False, queries="", domains="Финтех", extras=False, nonsense=True, fresh=True)
    asyncio.run(eval_live.main_async(args))

    before = json.loads((tmp_path / "live_eval_before.json").read_text(encoding="utf-8"))
    assert before["runs"][0]["query"] == "старый прогон"  # прежний отчёт сохранён, а не перезаписан
    runs = json.loads((tmp_path / "live_eval.json").read_text(encoding="utf-8"))["runs"]
    assert [r["query"] for r in runs[:2]] == eval_live.NONSENSE_QUERIES
    assert all(r["status"] == "rejected" and r["n_signals"] == 0 for r in runs[:2])
    fin = [r for r in runs if r["domain"] == "Финтех"]
    assert [r["mode"] for r in fin] == ["с базой отслеживания", "только обнаружение"]
    for r in fin:
        assert r["status"] == "done" and r["dataset_signals_in_domain"] == 17
        assert set(r["passport"]) == {"A", "B"} and "watch" in r and 0 <= r["recall_of_domain"] <= 1
        assert all(t["passport"] in ("A", "B") for t in r["top"])
    # В режиме мониторинга сигналы датасета без подтверждений уходят в «Наблюдать», а не в топ.
    assert fin[0]["watch"] > 0
