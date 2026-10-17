"""Задачи для LLM (GigaChat): расширение запроса, извлечение технологий, досье, резюме — на подставных ответах."""
import asyncio

from app.llm.providers import LLMResult, NoLLM
from app.llm.tasks import NAME_RU_RULE, extract_candidates, plan_query, summarize_sources, write_dossier


class ScriptedLLM(NoLLM):
    """Возвращает заранее заданный ответ и запоминает промпт."""

    provider, model = "gigachat", "GigaChat-2-Max"

    def __init__(self, answer: str, ok: bool = True):
        super().__init__()
        self.answer, self.ok, self.prompts = answer, ok, []

    async def complete(self, system, user, temperature=0.2, max_tokens=1500):
        self.prompts.append(user)
        return LLMResult(self.answer if self.ok else "", self.provider, self.model, 3, ok=self.ok)


def run(coro):
    return asyncio.run(coro)


def test_plan_mixes_llm_subtopics_with_checked_lexicon():
    llm = ScriptedLLM('{"topic_en": "fintech", "subqueries": ["agentic payments", "tokenized deposits", 7, "zk KYC"], "ru_terms": ["агентные платежи"]}')
    plan, res = run(plan_query(llm, "перспективные решения в финтехе"))
    assert plan["generated_by"] == "gigachat:GigaChat-2-Max" and res.ok
    assert plan["subqueries"][:3] == ["agentic payments", "tokenized deposits", "zk KYC"]  # нестроковое отброшено
    assert "stablecoin" in plan["subqueries"] and len(plan["subqueries"]) <= 12  # половина — из словаря области
    assert "«перспективные решения в финтехе»" in llm.prompts[0]


def test_plan_falls_back_to_lexicon_on_bad_answer():
    plan, res = run(plan_query(ScriptedLLM("не JSON"), "робототехника"))
    assert plan["generated_by"] == "lexicon" and "humanoid robot" in plan["subqueries"]


def test_extract_candidates_validates_document_numbers():
    llm = ScriptedLLM('[{"name_en": "tokenized deposits", "name_ru": "токенизированные депозиты", "docs": [0, 1, 99, "x"]}, {"name_ru": "без английского названия"}]')
    docs = [{"title": "A", "snippet": "s"}, {"title": "B", "snippet": "s"}]
    out, _ = run(extract_candidates(llm, "fintech", docs))
    assert out == [{"name_en": "tokenized deposits", "name_ru": "токенизированные депозиты", "doc_idx": [0, 1]}]
    assert NAME_RU_RULE in llm.prompts[0]  # правило для русских названий без машинных калек


def test_extract_candidates_salvages_broken_json():
    llm = ScriptedLLM('[\n"{\n"name_en": "zk KYC",\n"name_ru": "zk-KYC",\n"docs": [0]\n}"]')
    out, _ = run(extract_candidates(llm, "fintech", [{"title": "A"}]))
    assert out[0]["name_en"] == "zk KYC" and out[0]["doc_idx"] == [0]


def test_dossier_prompt_is_grounded_and_parsed():
    llm = ScriptedLLM('```json\n{"name_ru": "Токенизированные депозиты", "description": "Это ...", "risks": "Регулирование."}\n```')
    ev = [{"type": "preprint", "source": "arXiv", "date": "2026-01-01", "title": "Tokenized deposits", "snippet": "pilot"}]
    data, res = run(write_dossier(llm, "финтех", "tokenized deposits", ev, ["Научных работ: 12."]))
    assert data["name_ru"] == "Токенизированные депозиты" and res.ok
    p = llm.prompts[0]
    assert "ТОЛЬКО по этим документам" in p and "[1] (preprint, arXiv, 2026-01-01) Tokenized deposits" in p and "Научных работ: 12." in p


def test_dossier_failure_returns_none():
    data, res = run(write_dossier(ScriptedLLM("", ok=False), "q", "x", [], []))
    assert data is None and not res.ok


def test_summaries_keep_only_numbered_items():
    out, _ = run(summarize_sources(ScriptedLLM('{"0": "Резюме один", "1": "Резюме два", "x": "мусор"}'), [{"title": "a"}, {"title": "b"}]))
    assert out == {0: "Резюме один", 1: "Резюме два"}
