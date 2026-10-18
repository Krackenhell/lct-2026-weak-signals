"""Контрольный набор запросов: система не должна уверенно отвечать на бессмыслицу и не должна отказывать
в настоящих технологических направлениях (в том числе редких и англоязычных)."""
import pytest

from app.llm.tasks import fallback_plan, rule_check_query

TECH = [
    "перспективные решения в финтехе", "слабые сигналы в кибербезопасности ИИ", "инфраструктура для ИИ", "робототехника",
    "edge AI", "индустриальный ИИ", "энергетика и накопители", "квантовые вычисления", "микрофлюидика", "TinyML",
    "агентные платежи", "цифровые валюты центральных банков", "биотехнологии", "медицинские технологии", "спутниковая связь",
    "новые материалы для батарей", "нейроинтерфейсы", "post-quantum cryptography", "беспилотные грузовики", "синтетическая биология",
]
NOT_TECH = ["Привет", "привет, как дела?", "почему мирэа лучший вуз", "спасибо", "расскажи анекдот", "какая завтра погода", "ok", "?!"]


@pytest.mark.parametrize("q", TECH)
def test_technology_directions_are_accepted(q):
    assert rule_check_query(q)["ok"], q


@pytest.mark.parametrize("q", NOT_TECH)
def test_nonsense_is_rejected(q):
    v = rule_check_query(q)
    assert not v["ok"] and v["reason"], q


@pytest.mark.parametrize("q, expected", [
    ("перспективные решения в финтехе", "tokenization banking"),
    ("слабые сигналы в кибербезопасности ИИ", "prompt injection"),
    ("робототехника", "humanoid robot"),
    ("edge AI", "TinyML"),
    ("квантовые вычисления", "quantum error correction"),
])
def test_offline_plan_uses_domain_lexicon(q, expected):
    plan = fallback_plan(q)
    assert expected in plan["subqueries"] and 1 <= len(plan["subqueries"]) <= 10
    assert plan["generated_by"] == "lexicon"
