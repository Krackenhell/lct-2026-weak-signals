"""Сквозной тест в режиме «как на стенде»: GigaChat (понимание запроса, кандидаты, досье, резюме) +
decision-модель Jev (признаки, проверка документов и утверждений досье). Обе модели подставные и отвечают
в формате настоящих API — проверяется вся цепочка, включая перекрёстную проверку досье, без ключей и сети."""
import asyncio
import json
import re

import pytest

from app.db import SessionLocal
from app.decision.base import DecisionResult
from app.decision.heuristic import HeuristicDecision
from app.llm.providers import LLMResult, NoLLM
from app.models import Candidate, Document, ModelCall, Run
from app.pipeline import runner
from tests.fakes import TERMS, FakeWeb

FABRICATED = "Технологию уже внедрил крупнейший банк мира"
FAKE_QUOTE = "снижение затрат в десять раз по сравнению с SWIFT"


class FakeGigaChat(NoLLM):
    provider, model = "gigachat", "GigaChat-2-Max"

    def __init__(self, is_tech: bool = True):
        super().__init__()
        self.is_tech = is_tech

    async def complete(self, system, user, temperature=0.2, max_tokens=1500):
        if "Определи, является ли запрос" in user:
            out = {"is_tech": self.is_tech, "reason": "Это направление технологий." if self.is_tech else "Это бытовой вопрос, а не технологическое направление."}
        elif "Сформируй план поиска" in user:
            out = {"topic_en": "edge AI", "subqueries": ["on-device inference", "neuromorphic sensing", "chiplet design"], "ru_terms": ["периферийный ИИ"]}
        elif "Выдели КОНКРЕТНЫЕ технологии" in user:
            out = []
            for t in TERMS:
                idx = [int(i) for i, title in re.findall(r"^\[(\d+)\] (.*)$", user, flags=re.M) if t in title]
                if idx:
                    out.append({"name_en": t, "name_ru": f"{t} (рус.)", "docs": idx[:5]})
        elif "аналитическую справку" in user:
            name = re.search(r"Технология: «(.+?)»", user).group(1)
            out = {
                "name_ru": f"Технология {name}",
                "description": f"{name} описывается в нескольких независимых работах как прототип. {FABRICATED}.",
                "advantage": f"Авторы пишут «{FAKE_QUOTE}» [1].",
                "case_example": "В найденных документах описаны только исследовательские прототипы [1].",
                "why_weak_signal": "Работ мало, почти все свежие, массового внедрения нет.",
                "risks": "Неясна экономика.",
            }
        elif "Для каждого источника напиши резюме" in user:
            n = len(re.findall(r"^\[\d+\]", user, flags=re.M))
            out = {str(i): f"Краткое резюме источника {i}." for i in range(n)}
        else:
            return LLMResult("", self.provider, self.model, 1, ok=False, error="неизвестный промпт")
        return LLMResult(json.dumps(out, ensure_ascii=False), self.provider, self.model, 5)


class FakeJev:
    """Отвечает как Jev: признаки — по правилам, утверждения досье — подтверждает, кроме выдуманного."""

    provider, model = "jev", "jev-1.13.0"

    def __init__(self):
        self.rules = HeuristicDecision()

    async def ask(self, state, questions):
        base = await self.rules.ask(state, questions)
        answers = dict(base.answers)
        for qid, q in questions.items():
            if qid.startswith("claim_"):
                answers[qid] = {"type": "noul", "value": 0.05 if FABRICATED in q["instructions"] else 0.9}
        return DecisionResult(answers, self.provider, self.model, 7)


def _run(monkeypatch, query: str, llm) -> int:
    web = FakeWeb()
    monkeypatch.setattr(runner, "HttpClient", web.client)
    monkeypatch.setattr(runner, "get_llm", lambda: llm)
    monkeypatch.setattr(runner, "get_decision_model", lambda: FakeJev())
    with SessionLocal() as s:
        run = Run(query=query, options={})
        s.add(run)
        s.commit()
        rid = run.id
    asyncio.run(runner.execute(rid))
    return rid


@pytest.fixture(scope="module")
def stand_run():
    mp = pytest.MonkeyPatch()
    try:
        rid = _run(mp, "периферийный ИИ", FakeGigaChat())
        with SessionLocal() as s:
            data = (s.get(Run, rid), s.query(Candidate).filter_by(run_id=rid).all(), s.query(ModelCall).filter_by(run_id=rid).all(), s.query(Document).filter_by(run_id=rid).all())
            s.expunge_all()
        yield data
    finally:
        mp.undo()


def test_stand_mode_uses_both_models(stand_run):
    run, cands, calls, _ = stand_run
    assert run.status == "done", run.error
    assert run.providers["decision_model"] == "jev:jev-1.13.0" and run.providers["llm"] == "gigachat:GigaChat-2-Max"
    assert run.plan["generated_by"] == "gigachat:GigaChat-2-Max"
    assert run.stats["query_check"]["by"] == "gigachat:GigaChat-2-Max"
    purposes = {c.purpose for c in calls}
    assert {"проверка запроса", "расширение запроса", "извлечение технологий из документов", "ответы на вопросы-признаки и проверка документов",
            "аналитическое досье", "проверка утверждений досье"} <= purposes
    assert any("llm-extraction" in c.contributions["methods"] for c in cands)


def test_dossier_cross_check_removes_fabricated_claim_and_flags_fake_quote(stand_run):
    _, cands, _, _ = stand_run
    signals = [c for c in cands if c.status == "signal"]
    assert signals
    for c in signals:
        d = c.dossier
        assert d["generated_by"] == "gigachat:GigaChat-2-Max" and c.name_ru.startswith("Технология ")
        v = d["verification"]
        assert v["by"] == "jev:jev-1.13.0" and v["checked"] >= 3 and v["supported"] == v["checked"] - 1
        assert FABRICATED not in d["description"]  # выдуманное утверждение удалено
        assert "[цитата не найдена в источниках]" in d["advantage"]  # выдуманная цитата помечена
        assert {r["why"] for r in v["removed"]} == {"не подтверждено источниками", "цитата не найдена дословно"}


def test_foreign_sources_get_russian_summaries(stand_run):
    _, _, calls, docs = stand_run
    assert any(c.purpose == "резюме источников на русском" for c in calls)
    summarized = [d for d in docs if d.summary_ru]
    assert summarized and all(d.summary_generated and d.language != "ru" for d in summarized)


def test_gigachat_rejects_nonsense_with_its_own_reason(monkeypatch):
    rid = _run(monkeypatch, "лучшие вузы москвы", FakeGigaChat(is_tech=False))
    with SessionLocal() as s:
        run = s.get(Run, rid)
        assert run.status == "rejected" and run.error == "Это бытовой вопрос, а не технологическое направление."
        assert run.stats["query_check"]["by"].startswith("gigachat")
        assert s.query(Candidate).filter_by(run_id=rid).count() == 0
