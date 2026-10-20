"""Тесты проверяемости вывода: проверка запроса, паспорт доказательств, турникет, запас прочности,
окно для России, сверка досье, честная оценка. Без сети и без ключей моделей."""
import asyncio
import json
import math

from app.collectors.base import RawDoc
from app.config import get_settings
from app.decision.base import DecisionResult
from app.decision.heuristic import HeuristicDecision
from app.llm.providers import LLMResult, NoLLM
from app.llm.tasks import check_query, rule_check_query
from app.ml.model import SignalModel
from app.pipeline import passport as pp
from app.pipeline.decide import decide
from app.pipeline.evidence import Evidence
from app.pipeline.features import FEATURES
from app.pipeline.questions import EVENT, build_state, claim_questions, count_items, doc_questions, event_label


# ---------------------------------------------------------------- шаг 0: проверка запроса

def test_rules_reject_greetings_and_offtopic():
    for q in ["Привет", "привет!", "почему мирэа лучший вуз", "как дела", "ok"]:
        assert rule_check_query(q)["ok"] is False, q


def test_rules_accept_technology_directions():
    for q in ["перспективные решения в финтехе", "edge AI", "робототехника", "слабые сигналы в кибербезопасности ИИ", "квантовые вычисления", "микрофлюидика"]:
        assert rule_check_query(q)["ok"] is True, q


class FakeLLM(NoLLM):
    provider = "gigachat"
    model = "GigaChat-2-Max"

    def __init__(self, answer: str):
        super().__init__()
        self.answer = answer

    async def complete(self, system, user, temperature=0.2, max_tokens=1500):
        return LLMResult(self.answer, self.provider, self.model, 5)


def test_gigachat_verdict_is_used_and_greeting_is_guarded():
    v, _ = asyncio.run(check_query(FakeLLM('{"is_tech": false, "reason": "Это оценка вуза"}'), "лучшие вузы москвы"))
    assert v["ok"] is False and v["by"].startswith("gigachat")
    # Даже если модель ошиблась и сказала «да», явное приветствие не пропускаем.
    v, _ = asyncio.run(check_query(FakeLLM('{"is_tech": true, "reason": "ok"}'), "Привет"))
    assert v["ok"] is False
    # Битый ответ модели — работают правила.
    v, _ = asyncio.run(check_query(FakeLLM("не json"), "edge AI"))
    assert v["ok"] is True and v["by"] == "rules"


def test_no_llm_uses_rules():
    v, res = asyncio.run(check_query(NoLLM(), "Привет"))
    assert v["ok"] is False and res is None


# ---------------------------------------------------------------- паспорт доказательств

def _items(n, domains=None, types=None):
    domains = domains or [f"site{i}.org" for i in range(n)]
    types = types or ["preprint"] * n
    return [{"type": types[i], "source": "s", "url": f"https://{domains[i]}/a{i}", "title": f"work number {i}", "snippet": ""} for i in range(n)]


def _ans(confirmed: list[bool], event=0.0):
    a = {f"doc_{i + 1}": {"type": "noul", "value": 0.9 if c else 0.1} for i, c in enumerate(confirmed)}
    a["event"] = {"type": "score", "value": event}
    return a


def test_passport_levels():
    assert pp.passport(_items(6), _ans([True] * 6), 6)["level"] == "A"
    assert pp.passport(_items(4), _ans([True] * 3 + [False]), 4)["level"] == "B"
    assert pp.passport(_items(6), _ans([True, False, False, False, False, False]), 6)["level"] == "C"
    # Три новости с одного сайта — это не независимые подтверждения.
    same = _items(3, domains=["one.com"] * 3, types=["news"] * 3)
    assert pp.passport(same, _ans([True] * 3), 3)["level"] == "C"
    # А три разные научные работы на arXiv — независимые (разные группы), хоть домен и один.
    arx = _items(3, domains=["arxiv.org"] * 3)
    assert pp.passport(arx, _ans([True] * 3), 3)["level"] == "B"


def test_passport_ignores_dataset_links_and_unasked_items():
    items = _items(5, types=["dataset"] * 3 + ["preprint"] * 2)
    assert pp.passport(items, _ans([True] * 5), 5)["confirmed"] == 2
    # Вопросы заданы только по двум первым фрагментам (остальные не поместились в запрос).
    assert pp.passport(_items(6), _ans([True] * 6), 2)["confirmed"] == 2


def test_event_label_and_hard_event():
    assert event_label(0.0)[1] == "только обсуждения"
    assert event_label(1.0)[1] == "раунд инвестиций / сделка"
    p = pp.passport(_items(6, types=["news"] * 6), _ans([True] * 6, event=4 / 6), 6)
    assert p["hard_event"] and p["level"] == "A"  # нет науки, но есть пилот


# ---------------------------------------------------------------- турникет в decide

def _assessed(name, prob, level, n_docs=5):
    ev = Evidence(name, docs=[RawDoc(url=f"https://arxiv.org/abs/{i}", title="T", source_type="preprint") for i in range(n_docs)])
    answers = {"relevance": 0.9, "relevance_query": 0.9, "specific_tech": 0.9, "standard": 0.1, "mass_adoption": 0.1, "market_leaders": 0.1, "hype": 0.1}
    res = DecisionResult({k: {"type": "noul", "value": v} for k, v in answers.items()}, "test", "t", 0)
    passport = {"level": level, "confirmed": 1 if level == "C" else 5, "checked": 6, "domains": 1 if level == "C" else 4}
    return {"c": {"name_en": name}, "ev": ev, "items": [], "res": res, "features": {}, "prob": prob, "passport": passport}


def test_high_probability_without_evidence_goes_to_watch():
    model = SignalModel(features=list(FEATURES), mean=[0.0] * len(FEATURES), scale=[1.0] * len(FEATURES), coef=[0.1] * len(FEATURES), intercept=0.0, meta={})
    out = decide([_assessed("empty", 0.999, "C"), _assessed("solid", 0.8, "B")], model, top_k=15)
    assert out[0]["status"] == "watch" and out[0]["code"] == "watch"
    assert out[1]["status"] == "signal" and out[1]["rank"] == 1


def test_query_relevance_takes_minimum():
    model = SignalModel(features=list(FEATURES), mean=[0.0] * len(FEATURES), scale=[1.0] * len(FEATURES), coef=[0.1] * len(FEATURES), intercept=0.0, meta={})
    a = _assessed("drift", 0.9, "B")
    a["res"].answers["relevance_query"] = {"type": "score", "value": 0.1}  # к теме плана подходит, к запросу — нет
    out = decide([a], model, top_k=15)
    assert out[0]["code"] == "irrelevant"


def test_weakly_related_is_not_in_top_but_rules_keep_their_scale():
    model = SignalModel(features=list(FEATURES), mean=[0.0] * len(FEATURES), scale=[1.0] * len(FEATURES), coef=[0.1] * len(FEATURES), intercept=0.0, meta={})
    weak, rules = _assessed("quantum kernels", 0.98, "B"), _assessed("no topic words", 0.9, "B")
    weak["res"].answers["relevance_query"] = {"type": "score", "value": 0.42}  # между «слабо связано» и «связано»
    rules["res"].answers["relevance_query"] = {"type": "score", "value": 0.42}
    rules["res"].provider = "heuristic"  # у офлайн-правил 0,4 — это «совпадений слов нет», а не «слабо связано»
    out = decide([weak, rules], model, top_k=15)
    assert out[0]["code"] == "irrelevant"
    assert out[1]["status"] == "signal"


def test_foundation_models_are_technology_not_a_fund():
    from app.pipeline.decide import ORG

    assert not ORG.search("industrial time-series foundation models")
    assert not ORG.search("robot foundation-model")
    assert ORG.search("Linux Foundation") and ORG.search("foundation for AI safety")


# ---------------------------------------------------------------- вопросы decision-модели

def test_doc_and_claim_questions_answered_offline():
    items = [
        {"type": "preprint", "source": "arXiv", "date": "2026-09-01", "title": "Tokenized deposits pilot at a bank", "snippet": "tokenized deposits settlement pilot"},
        {"type": "news", "source": "x", "date": "2026-09-01", "title": "Weather report", "snippet": "rain"},
    ]
    state = build_state("tokenized deposits", "fintech", items)
    n = count_items(state)
    assert n == 2
    q = {**doc_questions(n), **claim_questions(["Tokenized deposits settlement pilot was launched"]), "event": EVENT}
    res = asyncio.run(HeuristicDecision().ask(state, q))
    assert res.answers["doc_1"]["value"] > 0.5 > res.answers["doc_2"]["value"]
    assert res.answers["claim_1"]["value"] >= 0.5
    assert event_label(res.answers["event"]["value"])[1] == "пилот / испытания"


# ---------------------------------------------------------------- запас прочности и вероятность

def test_robustness_is_exact_for_linear_model():
    contrib = [{"feature": "growth", "label": "Рост", "contribution": 3.0}, {"feature": "x", "label": "X", "contribution": 0.5}]
    r = pp.robustness(0.97, contrib)
    logit = math.log(0.97 / 0.03)
    assert abs(r["p_without"] - 1 / (1 + math.exp(-(logit - 3.0)))) < 1e-3
    assert r["level"] in ("strong", "stable", "fragile") and r["feature"] == "growth"
    assert pp.robustness(0.6, [{"feature": "g", "label": "G", "contribution": 2.0}])["level"] == "fragile"


def test_robustness_uses_full_logit_with_intercept():
    contrib = [{"feature": "a", "label": "A", "contribution": 3.0}, {"feature": "b", "label": "B", "contribution": 2.5}]
    r = pp.robustness(0.9999, contrib, intercept=0.0)  # логит 5.5, без «A» — 2.5 → 92%
    assert r["level"] == "strong" and abs(r["p_without"] - 1 / (1 + math.exp(-2.5))) < 1e-3


def test_out_of_distribution_feature_cannot_force_certainty():
    # Признак с крошечным разбросом в обучении: значение «другой» decision-модели не должно давать 100%.
    model = SignalModel(features=list(FEATURES), mean=[0.5] * len(FEATURES), scale=[0.01] * len(FEATURES), coef=[0.0] * len(FEATURES), intercept=0.0, meta={})
    model.coef[FEATURES.index("independent")] = -1.0
    p = model.predict({f: 0.5 for f in FEATURES} | {"independent": 0.15})  # z = −35 без ограничения
    assert p < 0.96
    assert max(abs(c["contribution"]) for c in model.explain({"independent": 0.15})) <= 3.0 + 1e-9


def test_prob_text_never_says_100():
    assert pp.prob_text(0.9996) == "выше 95%"
    assert "100" not in pp.prob_text(0.99999)
    assert pp.prob_text(0.8) == "в 80%"


# ---------------------------------------------------------------- мусорные фразы

def test_phrase_mining_drops_fragments():
    from app.pipeline import discovery

    def d(t):
        return RawDoc(url="u" + t, title=t, language="en")

    docs = [d("Show HN Open-source ledger"), d("Show HN Open-source ledger v2"), d("Rising adoption of digital wallets"), d("Rising adoption of digital banks"),
            d("Fraud detection and anti-money laundering"), d("Fraud detection and anti-money rules"), d("Fintech shares fall"), d("Fintech shares rise"),
            d("Tokenized deposits settle"), d("Tokenized deposits pilot")]
    names = [c["name_en"].lower() for c in discovery.mine_phrases(docs)]
    assert any("tokenized deposits" in n for n in names)
    assert not any(n.startswith("show hn") or n.endswith("digital") or "shares" in n or " and " in n for n in names), names


# ---------------------------------------------------------------- окно для России

def test_russia_window():
    assert pp.russia_window(40, 0)["status"] == "open"
    assert pp.russia_window(40, 2)["status"] == "closing"
    assert pp.russia_window(40, 12)["status"] == "closed"
    assert pp.russia_window(2, 0)["status"] == "thin"
    assert pp.russia_window(40, None)["status"] == "unknown"
    assert pp.russia_window(None, 3)["status"] == "unknown"  # OpenAlex недоступен — не «мало данных», а «нет данных»
    docs = [RawDoc(url="u", title="Токенизированные депозиты в банке", snippet=""), RawDoc(url="v", title="Погода", snippet="")]
    assert pp.mentions(docs, ["tokenized deposits", "токенизированные депозиты"]) == 1
    assert pp.world_recent_works({"2026": 10, "2025": 5, "2020": 99}, 2026) == 15


# ---------------------------------------------------------------- сверка досье

def test_unsupported_claims_and_fake_quotes_are_removed():
    dossier = {
        "description": "Технология позволяет проводить расчёты токенами. Её уже внедрил крупнейший банк мира.",
        "case_example": "В документе сказано «tokenized deposits settlement pilot» [1].",
        "advantage": "Авторы пишут «снижение затрат в десять раз по сравнению с SWIFT» [2].",
    }
    claims = pp.split_claims(dossier)
    answers = {f"claim_{i}": {"type": "noul", "value": 0.9} for i in range(1, len(claims) + 1)}
    bad = next(i for i, (_, s) in enumerate(claims, 1) if "крупнейший" in s)
    answers[f"claim_{bad}"]["value"] = 0.1
    out = pp.apply_verification(dossier, claims, answers, "Tokenized deposits settlement pilot at a bank", "jev:test")
    assert "крупнейший" not in out["description"]
    assert "[цитата не найдена" not in out["case_example"]  # дословная цитата есть в источнике
    assert "[цитата не найдена в источниках]" in out["advantage"]  # выдуманная — помечена
    assert out["verification"]["checked"] == len(claims) and out["verification"]["supported"] == len(claims) - 1


# ---------------------------------------------------------------- честная оценка

def test_metrics_are_honest():
    m = json.loads((get_settings().model_dir / "metrics.json").read_text(encoding="utf-8"))
    assert m["evidence_rule"] and m["n"] < m["reference_all_rows"]["n"]  # примеры без научной истории не участвуют
    assert "cv5_ci95" in m and m["cv5_ci95"]["f1"][0] < m["cv5"]["f1"] <= m["cv5_ci95"]["f1"][1]
    assert m["limitations"]
    for d, v in m["leave_one_domain_out"].items():
        assert v["n"] > 0 and not (v.get("f1") == 1.0 and "f1_ci95" not in v), d


def test_watchlist_off_by_default():
    assert get_settings().use_watchlist is False


def test_passport_reprints_and_preprint_twins_are_one_family():
    """Одна новость на пяти сайтах и одна работа на arXiv и в журнале — по одному подтверждению (замечание из разбора конкурентов)."""
    items = [{"type": "news", "source": "s", "url": f"https://site{i}.com/x", "title": "Acme raises $10M for solid-state batteries", "snippet": ""}
             for i in range(5)]
    p = pp.passport(items, _ans([True] * 5), 5)
    assert p["domains"] == 1 and p["reprints"] == 4 and p["level"] == "C"
    twins = [{"type": "preprint", "source": "arXiv", "url": "https://arxiv.org/abs/1", "title": "Halide electrolytes for ASSB", "snippet": ""},
             {"type": "science", "source": "Nature", "url": "https://doi.org/10.1/x", "title": "Halide Electrolytes for ASSB.", "snippet": ""},
             {"type": "science", "source": "JACS", "url": "https://doi.org/10.1/y", "title": "Another group, another result", "snippet": ""}]
    p = pp.passport(twins, _ans([True] * 3), 3)
    assert p["science"] == 2 and p["domains"] == 2


def test_no_hundred_percent_anywhere_in_texts():
    """Замечание экспертов финала: «откуда 100%». Ни вероятность, ни доли в текстах не выводятся как «100%»."""
    from app.pipeline.passport import prob_text, share_text

    assert share_text(1.0) == "все" and share_text(0.999) == "все" and share_text(0.0) == "ни одной" and share_text(0.81) == "81%"
    assert "100" not in prob_text(0.999) and "100" not in prob_text(1.0)
