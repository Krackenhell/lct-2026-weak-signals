"""Сквозной тест конвейера: запрос → корпус → кандидаты → доказательства → decision-модель → классификатор →
фильтры → паспорт → окно для России → сохранение. Сеть поддельная (tests/fakes.py), модели — офлайн-правила,
классификатор — настоящий обученный файл из data/model."""
import asyncio

import pytest

from app.collectors import http as http_mod
from app.config import get_settings
from app.db import SessionLocal
from app.models import Candidate, Document, ModelCall, Run
from app.pipeline import runner
from tests.fakes import TERMS, FakeWeb


async def _fake_links(urls, **_):
    # Одна «битая» ссылка на каждый прогон: проверяем, что она уходит из подтверждений.
    return {u: ("dead" if i == 0 else "ok") for i, u in enumerate(urls)}


def run_year() -> int:
    from datetime import date

    return date.today().year


def _execute(monkeypatch, query: str, web: FakeWeb | None = None, **options) -> int:
    web = web or FakeWeb()
    monkeypatch.setattr(runner, "HttpClient", web.client)
    monkeypatch.setattr(runner.links_mod, "check_all", _fake_links)  # проверку ссылок без сети тестирует test_links
    monkeypatch.setattr(get_settings(), "check_links", True)
    with SessionLocal() as s:
        run = Run(query=query, options=options)
        s.add(run)
        s.commit()
        run_id = run.id
    asyncio.run(runner.execute(run_id))
    return run_id


def _load(run_id: int):
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        cands = s.query(Candidate).filter_by(run_id=run_id).all()
        calls = s.query(ModelCall).filter_by(run_id=run_id).all()
        s.expunge_all()
    return run, cands, calls


@pytest.fixture(scope="module")
def edge_run():
    mp = pytest.MonkeyPatch()
    try:
        run_id = _execute(mp, "edge AI")
        yield _load(run_id)
    finally:
        mp.undo()


def test_pipeline_completes_and_stores_everything(edge_run):
    run, cands, calls = edge_run
    assert run.status == "done", run.error
    assert run.progress == 100 and run.finished_at is not None
    assert run.stats["candidates"] == len(cands) > 0
    assert run.stats["query_check"]["ok"] is True
    assert {"sources_processed", "documents_saved", "signals", "watch", "excluded", "passport", "http"} <= set(run.stats)
    assert run.providers["decision_model"].startswith("heuristic") and run.providers["llm"] == "none:template"
    # Каждое обращение decision-модели записано в журнал вместе с паспортом.
    feature_calls = [c for c in calls if c.purpose.startswith("ответы на вопросы-признаки")]
    assert len(feature_calls) == len(cands) and all("passport" in c.response for c in feature_calls)


def test_statuses_and_ranking_are_consistent(edge_run):
    run, cands, _ = edge_run
    assert {c.status for c in cands} <= {"signal", "watch", "excluded"}
    signals = sorted([c for c in cands if c.status == "signal"], key=lambda c: c.rank)
    assert len(signals) <= 15 and [c.rank for c in signals] == list(range(1, len(signals) + 1))
    assert run.stats["signals"] == len(signals)
    for c in cands:
        if c.status != "signal":
            assert c.rank is None and c.exclusion_code and c.exclusion_reason


def test_top_only_with_evidence_and_verifiability(edge_run):
    _, cands, _ = edge_run
    for c in cands:
        pp = c.contributions["passport"]
        assert pp["confirmed"] <= pp["checked"]
        if c.status == "signal":
            assert pp["level"] in ("A", "B"), c.name  # турникет: без доказательств в топ не попасть
            assert c.contributions["robustness"]["level"] in ("strong", "stable", "fragile")
            assert c.contributions["window"]["status"] in ("open", "closing", "closed", "thin", "unknown")
            assert c.probability is not None and c.probability >= 0.5
            assert "100%" not in (c.dossier.get("confidence_explanation") or "")
        if c.status == "watch":
            assert pp["level"] == "C"


def test_candidates_come_from_documents_and_mature_is_excluded(edge_run):
    _, cands, _ = edge_run
    by_name = {c.name.lower(): c for c in cands}
    # Кандидаты — ровно технологии, которые встречаются в документах корпуса (без обрывков фраз).
    assert set(by_name) == {t.lower() for t in TERMS}
    # «Зрелая»: десятки тысяч работ за 26 лет и популярная статья Википедии → исключена с понятной причиной.
    mature = by_name["federated analytics"]
    assert mature.status == "excluded" and mature.exclusion_code == "mature" and "Зрелая" in mature.exclusion_reason
    # Окно для России: в мире публикации есть, в русскоязычных источниках — нет.
    assert by_name["chiplet interconnect fabrics"].contributions["window"]["status"] == "open"
    # Технология, по которой точный поиск ничего не нашёл, не становится сигналом («нет данных» ≠ «ранний сигнал»).
    empty = by_name["spiking photonic processors"]
    assert empty.status != "signal" and empty.exclusion_code in ("low_probability", "watch", "low_evidence")
    # Ряд публикаций по годам сохраняется для графика в карточке; радар банка — у каждого сигнала.
    chip = by_name["chiplet interconnect fabrics"]
    assert [d["year"] for d in chip.contributions["dynamics"]][-1] == run_year() and chip.contributions["radar"]["ring"] in ("Пилотировать", "Изучать")


def test_dead_links_are_removed_from_evidence(edge_run):
    _, cands, _ = edge_run
    signals = [c for c in cands if c.status == "signal"]
    links = [c.contributions["passport"]["links"] for c in signals]
    assert sum(lnk["dead"] for lnk in links) == 1 and all(lnk["ok"] > 0 for lnk in links)
    with SessionLocal() as s:
        shown = [s.get(Document, i) for c in signals for i in c.document_ids]
        assert shown and all(d.link_status != "dead" for d in shown)  # битая ссылка не показывается как подтверждение


def test_pure_discovery_by_default(edge_run):
    run, cands, _ = edge_run
    assert not (run.options or {}).get("use_watchlist")
    assert all(c.origin == "discovered" for c in cands)


def test_rerun_shows_monitoring_changes(monkeypatch, edge_run):
    first, _, _ = edge_run
    run_id = _execute(monkeypatch, "Edge AI")  # регистр не важен
    run, _, _ = _load(run_id)
    ch = run.stats["changes"]
    assert ch and ch["prev_run_id"] >= first.id
    assert ch["kept"] + len(ch["new"]) == run.stats["signals"]


def test_nonsense_query_is_rejected_without_work(monkeypatch):
    web = FakeWeb()
    run_id = _execute(monkeypatch, "Привет", web)
    run, cands, calls = _load(run_id)
    assert run.status == "rejected" and "не похож" in run.error
    assert cands == [] and calls == [] and web.calls == []  # ни одного запроса к источникам


def test_sources_down_do_not_break_the_run(monkeypatch):
    async def no_sleep(_):
        return None

    monkeypatch.setattr(http_mod.asyncio, "sleep", no_sleep)
    web = FakeWeb(down={"api.openalex.org", "api.gdeltproject.org", "habr.com"})
    run_id = _execute(monkeypatch, "робототехника", web)
    run, cands, _ = _load(run_id)
    assert run.status == "done", run.error
    assert run.stats["http"]["api.openalex.org"]["failed"] > 0
    for c in cands:
        if c.status == "signal":
            # OpenAlex недоступен — окно для России честно «нет данных», а не «окно открыто».
            assert c.contributions["window"]["status"] == "unknown"


def test_monitoring_mode_adds_watchlist_but_dataset_links_do_not_count(monkeypatch):
    run_id = _execute(monkeypatch, "перспективные решения в финтехе", use_watchlist=True)
    run, cands, _ = _load(run_id)
    assert run.status == "done", run.error
    watched = [c for c in cands if "watchlist" in c.contributions["methods"]]
    assert len(watched) >= 10, "в режиме мониторинга должны быть сигналы из базы отслеживания"
    # Главное: сигналы датасета, по которым в источниках нет подтверждений, НЕ попадают в топ «по 100%»,
    # даже когда классификатор даёт им высокую вероятность, — они уходят в «Наблюдать».
    unconfirmed = [c for c in watched if c.contributions["passport"]["level"] == "C"]
    assert unconfirmed and all(c.status in ("watch", "excluded") for c in unconfirmed)
    assert any(c.status == "watch" and c.probability > 0.9 for c in unconfirmed)
    assert run.stats["watch"] == sum(1 for c in cands if c.status == "watch")
    # Ссылки из датасета организатора не считаются подтверждением.
    assert all(c.contributions["passport"]["confirmed"] <= 1 for c in unconfirmed)
