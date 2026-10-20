"""REST API: контракты, которые использует интерфейс, и путь «запрос → отказ» целиком через HTTP."""
import time

import pytest
from fastapi.testclient import TestClient

from app.db import SessionLocal
from app.main import app
from app.models import Candidate, Document, ModelCall, Run


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def sample_run():
    """Готовый прогон в БД: сигнал, кандидат «наблюдать», исключённый, документ, вызов модели."""
    with SessionLocal() as s:
        run = Run(query="api-тест квантовые сенсоры", status="done", progress=100, stats={"signals": 1, "passport": {"A": 1, "B": 0}}, providers={"decision_model": "jev:jev-latest", "llm": "gigachat:GigaChat-2-Max"}, options={})
        s.add(run)
        s.flush()
        doc = Document(run_id=run.id, url="https://arxiv.org/abs/1", title="Quantum sensing", source_name="arXiv", source_type="preprint", trust_level="medium", collector="arxiv")
        s.add(doc)
        s.flush()
        pp = {"level": "A", "label": "Надёжно", "checked": 6, "confirmed": 6, "domains": 3, "domain_list": ["arxiv.org"], "science": 3, "event_level": 4, "event": "пилот / испытания", "hard_event": True}
        items = [{"feature": "growth", "label": "Рост", "value": 1.2, "contribution": 0.9, "level": "высокое"}, {"feature": "hype", "label": "Шум", "value": 0.1, "contribution": -0.2, "level": "низкое"}]
        sig = Candidate(run_id=run.id, name="quantum sensing", status="signal", rank=1, probability=0.91, relevance=0.8, features={"log_total_works": 3.0},
                        contributions={"items": items, "methods": ["llm-extraction"], "passport": pp, "robustness": {"level": "strong", "label": "прочный", "text": "t", "p_without": 0.8}},
                        answers={"novelty": {"type": "noul", "value": 0.9}, "doc_1": {"type": "noul", "value": 0.9}}, dossier={"description": "d"}, document_ids=[doc.id])
        watch = Candidate(run_id=run.id, name="thin thing", status="watch", probability=0.97, exclusion_code="watch", exclusion_reason="мало", contributions={"items": [], "passport": {**pp, "level": "C"}})
        exc = Candidate(run_id=run.id, name="iso 20022", status="excluded", probability=0.3, exclusion_code="standard", exclusion_reason="стандарт", contributions={"items": []})
        s.add_all([sig, watch, exc, ModelCall(run_id=run.id, provider="jev", model="jev-latest", purpose="ответы на вопросы-признаки", subject="quantum sensing")])
        s.commit()
        return run.id, sig.id


def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


@pytest.mark.parametrize("body", [{"query": "x"}, {"query": ""}, {"query": "a" * 301}, {}])
def test_search_validates_input(client, body):
    assert client.post("/api/search", json=body).status_code == 422


def test_run_splits_signals_watch_excluded(client, sample_run):
    run_id, _ = sample_run
    r = client.get(f"/api/runs/{run_id}").json()
    assert [c["name"] for c in r["signals"]] == ["quantum sensing"]
    assert [c["name"] for c in r["watch"]] == ["thin thing"]
    assert [c["exclusion_code"] for c in r["excluded"]] == ["standard"]
    sig = r["signals"][0]
    assert sig["passport"]["level"] == "A" and sig["robustness"]["label"] == "прочный"
    assert [p["feature"] for p in sig["key_predictors"]] == ["growth"]  # только доводы «за»
    assert r["excluded"][0]["exclusion_label"] == "Отраслевой стандарт"


def test_candidate_details_and_sources(client, sample_run):
    _, cand_id = sample_run
    c = client.get(f"/api/candidates/{cand_id}").json()
    assert c["query"].startswith("api-тест") and c["sources"][0]["trust_level_ru"]
    assert c["answers"]["novelty"]["label"] == "Новизна"
    assert len(c["contributions"]) == 2


def test_not_found(client):
    assert client.get("/api/runs/999999").status_code == 404
    assert client.get("/api/candidates/999999").status_code == 404


def test_log_and_showcase(client, sample_run):
    run_id, _ = sample_run
    assert client.get(f"/api/runs/{run_id}/log").json()[0]["provider"] == "jev"
    show = client.get("/api/showcase").json()
    item = next(s for s in show if s["run_id"] == run_id)
    assert item["signals"] == 1 and item["mode"] == "обнаружение" and item["passport"]["A"] == 1
    assert len({s["query"].lower() for s in show}) == len(show)  # одна карточка на тему
    assert all(not s["providers"].get("decision_model", "").startswith("heuristic") for s in show)  # запасные прогоны не показываются
    # Для главной — только темы-примеры: случайный запрос посетителя туда не попадает.
    assert all(s["run_id"] != run_id for s in client.get("/api/showcase?examples=1").json())


def test_showcase_prefers_current_model_run(client, monkeypatch):
    from app.config import get_settings

    s = get_settings()
    monkeypatch.setattr(s, "llm_provider", "gigachat")
    monkeypatch.setattr(s, "gigachat_auth_key", "k")
    monkeypatch.setattr(s, "gigachat_model", "GigaChat-2")
    ids = {}
    with SessionLocal() as db:
        for model in ("GigaChat-2", "GigaChat-2-Max"):  # пробный прогон на Max — более поздний
            r = Run(query="витрина: выбор модели", status="done", stats={"signals": 3}, options={},
                    providers={"decision_model": "jev:jev-latest", "llm": f"gigachat:{model}"})
            db.add(r)
            db.commit()
            ids[model] = r.id
    item = next(x for x in client.get("/api/showcase").json() if x["query"] == "витрина: выбор модели")
    assert item["run_id"] == ids["GigaChat-2"]  # на главной — прогон рабочей модели, хотя прогон на Max свежее
    monkeypatch.setattr(s, "gigachat_model", "GigaChat-2-Max")
    item = next(x for x in client.get("/api/showcase").json() if x["query"] == "витрина: выбор модели")
    assert item["run_id"] == ids["GigaChat-2-Max"]


def test_model_info_exposes_honest_metrics(client):
    m = client.get("/api/model").json()
    assert m["trained"] and m["metrics"]["min_docs"] >= 3 and m["metrics"]["limitations"]
    assert m["exclusion_codes"]["watch"].startswith("Наблюдать")


def test_nonsense_query_rejected_through_http(client):
    run = client.post("/api/search", json={"query": "Привет"}).json()
    for _ in range(50):
        r = client.get(f"/api/runs/{run['id']}").json()
        if r["status"] not in ("queued", "running"):
            break
        time.sleep(0.1)
    assert r["status"] == "rejected" and r["signals"] == [] and r["error"]


def test_spa_routes_served(client):
    # Интерфейс отдаётся самим backend: прямые ссылки на страницы открываются без nginx.
    r = client.get("/runs/1")
    assert r.status_code == 200 and "<div id=" in r.text


def test_list_summary_is_first_sentence_without_refs_or_template():
    from app.api.routes import _first_sentence

    assert _first_sentence("Ромбоэдрический графен [1, 2] — многослойная модификация. Второе предложение.") == "Ромбоэдрический графен — многослойная модификация."
    assert _first_sentence("«x» — технология, выявленная в документах по запросу. Подробнее — позже.") == ""
