"""Протоколы проверки гипотез П1–П8 из docs/research/ИССЛЕДОВАНИЕ_И_ГИПОТЕЗЫ.md (офлайн-часть, без сети)."""
import asyncio
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from app.collectors.grants import strip_program_prefix
from app.collectors.http import HOST_TTL_HOURS, HttpClient, prune_cache
from app.config import get_settings
from app.db import SessionLocal
from app.llm import tasks
from app.llm.tasks import fallback_plan, is_broad, plan_query, translate_roots
from app.llm.terms import check_name_ru
from app.models import Candidate, Run
from app.pipeline import decide as decide_mod
from app.pipeline import discovery, routing, runner
from app.pipeline.decide import PAPER_TITLE, decide, near_duplicate, query_anchors, rank_score
from app.pipeline.passport import card_facts, evidence_checks, mentions, russia_window
from tests.fakes import FakeWeb
from tests.test_llm_tasks import ScriptedLLM, run

# ---------------------------------------------------------------- П1. Планировщик узких запросов

BROAD = ["перспективные решения в финтехе", "слабые сигналы в кибербезопасности ИИ", "робототехника", "edge AI и вычисления на устройствах",
         "инфраструктура для ИИ", "индустриальный ИИ", "энергетика", "медицина", "материалы", "квантовые вычисления", "кибербезопасность"]
NARROW = ["технологии многослойного графена", "микрофлюидные чипы", "микрофлюидные устройства", "органы на чипе", "лаборатория на чипе для диагностики",
          "квантовые сенсоры для медицины", "твердотельные аккумуляторы", "перовскитные солнечные элементы", "нейроморфные чипы", "биопечать",
          "гибкие устройства на графене", "мРНК-вакцины", "спинтроника", "биосенсоры", "термоядерный синтез", "агентные платежи",
          "беспилотные грузовики", "нейроинтерфейсы", "CRISPR-диагностика", "графеновые мембраны для опреснения"]
LEXICON_TERMS = {t.lower() for terms in tasks.DOMAIN_LEXICON.values() for t in terms}


@pytest.mark.parametrize("q", BROAD)
def test_broad_queries_keep_lexicon_plan(q):
    """T1, регрессия: для 6 доменов датасета и широких тем план без LLM — прежний словарный."""
    plan = fallback_plan(q)
    assert is_broad(q) and plan["broad"] and plan["generated_by"] == "lexicon"
    assert any(s.lower() in LEXICON_TERMS for s in plan["subqueries"])


@pytest.mark.parametrize("q", NARROW)
def test_narrow_query_plan_has_no_lexicon_and_no_cyrillic(q):
    """T2: узкий запрос — подзапросы LLM без словаря, сам предмет по-английски первым, без кириллицы, без доменов watchlist."""
    llm = ScriptedLLM(json.dumps({
        "query_en": ["subject term EN"], "topic_en": "subject area",
        "subqueries": ["AI accelerator", "variant one", "subject term variants", "квантовые штуки", "variant two"],
        "ru_terms": ["русская фраза"],
    }, ensure_ascii=False))
    plan, _ = run(plan_query(llm, q))
    assert not is_broad(q) and plan["broad"] is False
    assert plan["subqueries"][0] == "subject term EN" and plan["topic_en"] == "subject term EN"
    assert not any(tasks.re.search(r"[а-яё]", s, tasks.re.I) for s in plan["subqueries"])
    assert not [s for s in plan["subqueries"] if s.lower() in LEXICON_TERMS - {"ai accelerator"}]  # словарь не подмешан
    assert plan["subqueries"].index("subject term variants") < plan["subqueries"].index("variant one")  # делящие слово с запросом — вперёд
    assert discovery.watchlist(q, plan, enabled=True) == [] or all(
        len(set(tasks.re.findall(r"[a-z]{4,}", c["name_en"].lower())) & set(tasks.re.findall(r"[a-z]{4,}", " ".join(plan["subqueries"]).lower()))) >= 2
        for c in discovery.watchlist(q, plan, enabled=True))


@pytest.mark.parametrize("q, expected", [
    ("технологии многослойного графена", "multilayer graphene"), ("микрофлюидные чипы", "microfluidic chip"),
    ("органы на чипе", "organ-on-a-chip"), ("перовскитные солнечные элементы", "perovskite solar cell"),
    ("твердотельные аккумуляторы", "solid-state battery"), ("газлифт", "gas lift"),
])
def test_offline_narrow_plan_translates_by_roots(q, expected):
    """T3, LLM выключена: первый подзапрос — английский термин запроса."""
    plan = fallback_plan(q)
    assert plan["subqueries"][0] == expected and plan["topic_en"] == expected


def test_root_translation_refuses_half_translation():
    assert translate_roots("квантовые сенсоры для медицины") == ""  # «медицины» нет в словаре — полуперевод хуже Википедии
    plan = fallback_plan("квантовые сенсоры для медицины")
    assert plan["backup"] and "quantum sensing" in plan["subqueries"]  # запасные подтемы, отбрасываются при найденном термине


@pytest.mark.parametrize("q", ["микрофлюидные чипы", "органы на чипе", "биосенсоры", "лаборатория на чипе"])
def test_life_science_routing(q):
    """T4: науки о жизни включают Europe PMC (раньше микрофлюидика его не включала)."""
    assert routing.profile(q) == "life_med" and routing.route(q)["europepmc_corpus"]


def test_prompts_do_not_contain_dataset_terms():
    """T5: в примерах промптов нет фраз из датасета организатора (иначе выглядит как подгонка под ответ)."""
    terms = json.loads((Path(get_settings().seed_dir) / "positive_terms.json").read_text(encoding="utf-8"))
    phrases = {p.lower() for k, v in terms.items() if not k.startswith("_") for p in v if len(p) > 6}
    llm = ScriptedLLM("[]")
    run(plan_query(llm, "x"))
    run(tasks.extract_candidates(llm, "x", [{"title": "t"}]))
    text = " ".join(llm.prompts).lower()
    assert not [p for p in phrases if p in text]


# ---------------------------------------------------------------- П2. Разнообразие с учётом запроса

class _Res:
    def __init__(self, answers, provider="jev"):
        self.answers, self.ok, self.provider = answers, True, provider


class _Ev:
    def __init__(self, n=6):
        from app.collectors.base import RawDoc

        self.docs = [RawDoc(url=f"https://arxiv.org/abs/{i}", title=f"t{i}", source_name="arXiv", source_type="preprint", collector="arxiv") for i in range(n)]
        self.failed = []


def _cand(name, p=0.9, rel=0.9):
    ans = {k: {"value": v} for k, v in {"relevance": rel, "relevance_query": rel, "evidence_match": 0.9, "is_technology": 0.9, "product_name": 0.1,
                                          "specific_tech": 0.8, "standard": 0.1, "mass_adoption": 0.1, "market_leaders": 0.1, "hype": 0.1}.items()}
    return {"c": {"name_en": name, "methods": ["llm-extraction"]}, "res": _Res(ans), "features": {"log_total_works": 3.0}, "prob": p,
            "ev": _Ev(), "passport": {"level": "A", "confirmed": 6, "checked": 8, "domains": 3}, "missing": []}


GRAPHENE = ["rhombohedral multilayer graphene", "twisted multilayer graphene", "multilayer graphene moire superlattices", "graphene chern insulators",
            "chiral superconductivity in graphene", "multilayer graphene intercalation", "CVD multilayer graphene growth", "graphene nanoribbons",
            "graphene quantum dots", "multilayer graphene photodetectors", "graphene heterostructure transistors", "graphene oxide membranes"]
GRAPHENE_PLAN = {"query_en": ["multilayer graphene"], "topic_en": "multilayer graphene", "generated_by": "gigachat:GigaChat-2",
                 "subqueries": ["multilayer graphene", "rhombohedral graphene", "twisted graphene", "graphene moire", "graphene intercalation", "graphene photonics"]}


def test_graphene_topic_is_not_crowded_out():
    """(a) 12 графеновых технологий: ≥ 10 сигналов, 0 «crowded» на graphene / multilayer."""
    anchors = query_anchors(GRAPHENE_PLAN, "технологии многослойного графена")
    assert {"graphene", "multilayer"} <= anchors
    out = decide([_cand(n, p=0.9 - i * 0.01) for i, n in enumerate(GRAPHENE)], None, 15, topic_terms=["multilayer graphene"], anchors=anchors)
    assert sum(d["status"] == "signal" for d in out) >= 10
    assert not [d for d in out if d.get("code") == "crowded" and any(w in d["reason"] for w in ("graphene", "multilayer"))]


def test_microfluidic_terms_are_not_paper_titles():
    """(b) «lab on a chip platforms» и «organ on a chip devices» — не заголовки статей; (g) настоящие заголовки ловятся."""
    for name in ("lab on a chip platforms", "organ on a chip devices", "human in the loop control", "software as a service platforms"):
        assert not PAPER_TITLE.search(name), name
    for name in ("Towards Scalable Graphene Growth", "Stackelberg Model of AI Security", "A Survey of microfluidics"):
        assert PAPER_TITLE.search(name), name


def test_anchor_found_only_through_subqueries():
    """(b2) тема «Lab-on-a-chip technologies», 4 из 6 подзапросов с «microfluidic»: 0 «crowded»."""
    plan = {"topic_en": "Lab-on-a-chip technologies", "generated_by": "gigachat:GigaChat-2",
            "subqueries": ["droplet microfluidic", "paper microfluidic", "microfluidic sensors", "organ chips", "microfluidic cell sorting", "point of care"]}
    names = ["droplet microfluidic chips", "paper microfluidic assays", "microfluidic impedance cytometry", "microfluidic cell sorting", "inertial microfluidic focusing", "digital microfluidic platforms"]
    out = decide([_cand(n) for n in names], None, 15, anchors=query_anchors(plan, "лаборатория на чипе"))
    assert not [d for d in out if d.get("code") == "crowded"]


def test_ai_infrastructure_still_limits_quantum():
    """(c) для «инфраструктура для ИИ» «quantum» не якорь: квантовых в топе не больше 3."""
    plan = {"topic_en": "AI infrastructure", "generated_by": "gigachat:GigaChat-2", "subqueries": ["AI accelerator", "optical interconnect", "KV cache", "chiplet", "photonic computing", "CXL memory"]}
    names = ["quantum annealing scheduling", "quantum kernel methods", "quantum reservoir computing", "quantum error mitigation", "quantum neural accelerators",
             "optical circuit switching", "KV cache offloading"]
    out = decide([_cand(n) for n in names], None, 15, anchors=query_anchors(plan, "инфраструктура для ИИ"))
    assert sum(d["status"] == "signal" and "quantum" in n for d, n in zip(out, names, strict=True)) <= 3


def test_query_echo_and_solid_state_triplet():
    """(d) сам термин запроса исключён, направление внутри — нет; (e) из твердотельной тройки остаётся одна."""
    out = decide([_cand("multilayer graphene"), _cand("rhombohedral multilayer graphene")], None, 15, topic_terms=["multilayer graphene"])
    assert out[0]["code"] == "topic_itself" and out[1]["status"] == "signal"
    assert near_duplicate("solid-state batteries", "solid-state battery technology")
    out = decide([_cand("solid-state batteries", 0.9), _cand("solid-state battery technology", 0.8), _cand("solid-state battery systems (SSB)", 0.7)], None, 15)
    assert sum(d["status"] == "signal" for d in out) == 1


def test_lexicon_plan_disables_crowding_in_runner_rule():
    """(f) при словарном плане без термина из литературы правило «3 на тему» не применяется."""
    names = [f"widget sensing method {i}" for i in range(6)]
    out = decide([_cand(n) for n in names], None, 15, crowding=False)
    assert not [d for d in out if d.get("code") == "crowded"]


# ---------------------------------------------------------------- П3. Честный режим при сбое OpenAlex, бюджет

class RecordingWeb(FakeWeb):
    def handler(self, request: httpx.Request) -> httpx.Response:
        self.urls = getattr(self, "urls", [])
        self.urls.append(str(request.url))
        return super().handler(request)


def _execute(query: str, web: FakeWeb, monkeypatch) -> int:
    monkeypatch.setattr(runner, "HttpClient", web.client)
    with SessionLocal() as s:
        r = Run(query=query, options={})
        s.add(r)
        s.commit()
        rid = r.id
    asyncio.run(runner.execute(rid))
    return rid


def test_openalex_outage_is_reported_not_imputed(monkeypatch):
    """(a) OpenAlex не отвечает: прогон завершается, degraded=true, подставленные числа не выдаются за факты, повторно не отдаётся."""
    from app.api.routes import _cand_out, reuse_blockers

    rid = _execute("edge AI сбой OpenAlex", FakeWeb(down=("api.openalex.org",)), monkeypatch)
    with SessionLocal() as s:
        r = s.get(Run, rid)
        assert r.status == "done", r.error
        assert r.stats["degraded"] and r.stats["openalex"]["imputed_share"] > 0.2
        cands = s.query(Candidate).filter_by(run_id=rid).all()
        assert cands and all("openalex" in (c.contributions or {}).get("missing", []) for c in cands)
        for c in cands:
            assert "найдено около" not in c.dossier.get("why_weak_signal", "")
            assert _cand_out(c)["first_year"] is None  # возраст темы — среднее обучающей выборки, год не показываем
        assert "статистика публикаций OpenAlex была недоступна" in reuse_blockers(r)


def test_country_counts_only_for_signals(monkeypatch):
    """(b) география считается после решения и только для сигналов."""
    web = RecordingWeb()
    rid = _execute("edge AI география", web, monkeypatch)
    with SessionLocal() as s:
        n_signals = s.query(Candidate).filter_by(run_id=rid, status="signal").count()
    calls = [u for u in web.urls if "group_by=authorships.institutions.country_code" in u]  # запросы стран (не организаций России)
    assert len(calls) == n_signals


def test_openalex_cache_lives_longer_than_other_hosts(tmp_path):
    """(c) файл OpenAlex возрастом 100 ч отдаётся из кэша и переживает prune_cache; файл другого хоста той же давности — нет."""
    h = HttpClient()
    h._cache_dir = tmp_path
    hits = []
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: hits.append(req.url.host) or httpx.Response(200, json={"fresh": True})))
    h._interval = {}
    old = time.time() - 100 * 3600
    for url in ("https://api.openalex.org/works", "https://export.arxiv.org/api/query"):
        p = h._cache_path(url, {"q": "x"})
        p.write_text(json.dumps({"cached": True}), encoding="utf-8")
        os.utime(p, (old, old))
    assert asyncio.run(h.get("https://api.openalex.org/works", {"q": "x"})) == {"cached": True}
    assert asyncio.run(h.get("https://export.arxiv.org/api/query", {"q": "x"})) == {"fresh": True}
    asyncio.run(h.close())
    assert HOST_TTL_HOURS["api.openalex.org"] > 100
    p_oa = h._cache_path("https://api.openalex.org/works", {"q": "x"})
    os.utime(p_oa, (old, old))
    prune_cache(tmp_path, 72)
    assert p_oa.exists()


# ---------------------------------------------------------------- П4. Понятная уверенность и видимое ранжирование

def test_rank_score_never_reaches_one_and_is_monotone():
    """Насыщенные p (0,999 / 0,991 / 0,96) при разной релевантности: место решает релевантность, балл ≤ 0,95."""
    rows = [(0.999, 0.6), (0.991, 1.0), (0.96, 0.9)]
    scores = [rank_score(p, r) for p, r in rows]
    assert max(scores) <= 0.95 and rank_score(0.99999, 1.0) == 0.95
    out = decide([_cand(n, p, r) for n, (p, r) in zip(["droplet sorting", "perovskite tandems", "graphene membranes"], rows, strict=True)], None, 15)
    order = sorted(range(3), key=lambda i: out[i]["rank"])
    assert [round(out[i]["score"]["final"], 4) for i in order] == sorted((round(s, 4) for s in scores), reverse=True)
    low = decide([_cand("weak tech", 0.4)], None, 15)[0]
    assert low["status"] == "excluded" and "rank" not in low


def test_evidence_checks_k_of_5():
    pp = {"confirmed": 6, "domains": 3, "science": 2, "event_level": 3, "links": {"ok": 4, "restricted": 0, "dead": 0}}
    assert evidence_checks(pp)["passed"] == 5 and evidence_checks(pp)["total"] == 5
    c = evidence_checks({"confirmed": 3, "domains": 2, "science": 0, "event_level": 1})
    assert c["passed"] == 0 and c["measured"] == 4  # ссылки не проверялись — «не измерено», а не провал


def test_no_100_percent_anywhere_in_card():
    from app.pipeline.passport import prob_text, robustness

    assert "100" not in prob_text(0.99999)
    rb = robustness(0.9999, [{"feature": "growth", "label": "Рост", "contribution": 3.0}, {"feature": "age_years", "label": "Возраст", "contribution": 1.0}], intercept=2.0)
    assert "100%" not in rb["text"]


# ---------------------------------------------------------------- П5. Русские названия

@pytest.mark.parametrize("en, ru", [
    ("prompt injection detection model", "Обнаружение инъекций prompts"),
    ("transformer-based anomaly detection", "Трансформер-базированное обнаружение аномалий"),
    ("physically unclonable functions in IoT", "Физически неуникальные функции в IoT"),
    ("over-the-air computation", "Масштабируемая цифровая удалённая вычислительная обработка"),
])
def test_validator_rejects_calques(en, ru):
    shown, why = check_name_ru(en, ru)
    assert shown == en and why


@pytest.mark.parametrize("en, ru", [
    ("graphene quantum dots", "Графеновые квантовые точки"), ("MXene quantum dots", "MXene квантовые точки"),
    ("in-sensor computing", "вычисления в сенсоре (In-Sensor Computing)"), ("medical microrobots", "Медицинские микророботы"),
])
def test_validator_keeps_good_names(en, ru):
    assert check_name_ru(en, ru) == (ru, None)


def test_federated_edge_calque_fixed_and_query_leak_rejected():
    assert check_name_ru("federated learning at edge", "Федеративное обучение на краях")[0] == "Федеративное обучение на периферии"
    shown, why = check_name_ru("droplet sorting", "капельная сортировка для микрофлюидные чипы", query="микрофлюидные чипы")
    assert shown == "droplet sorting" and "запроса" in why


def test_watchlist_name_survives_merge():
    merged = discovery.merge([
        {"name_en": "purpose bound money", "name_ru": "Цельносвязанные деньги", "doc_idx": [1], "method": "llm-extraction"},
        {"name_en": "purpose-bound money", "name_ru": "Целевые деньги (Purpose-Bound Money)", "doc_idx": [], "method": "watchlist", "watch_id": 7},
    ])
    assert len(merged) == 1 and merged[0]["name_ru"] == "Целевые деньги (Purpose-Bound Money)" and merged[0]["watch_id"] == 7


def test_russia_window_wording_and_declension():
    assert russia_window(30, 0)["label"] == "Упоминаний на русском не найдено"

    class D:
        title, snippet = "Обзор твердотельных аккумуляторов для электромобилей", ""

    assert mentions([D()], ["твердотельные аккумуляторы"]) == 1  # падежи: раньше 0 и ложное «окно открыто»


# ---------------------------------------------------------------- П6–П8

def test_examples_are_precomputed_topics():
    from app import precompute
    from app.examples import EXAMPLES

    assert precompute.DEFAULT_QUERIES is EXAMPLES and "технология многослойного графена" in EXAMPLES and "микрофлюидные чипы" in EXAMPLES


def test_plan_model_view_shares_client_and_labels(monkeypatch):
    """П7: модель плана подменяется в теле запроса, клиент и подпись — общие для прогона и повторной выдачи."""
    from app.llm import providers

    monkeypatch.setenv("LLM_PROVIDER", "gigachat")
    monkeypatch.setenv("GIGACHAT_AUTH_KEY", "test-not-a-key")
    monkeypatch.setenv("GIGACHAT_MODEL_PLAN", "GigaChat-2-Max")
    get_settings.cache_clear()
    try:
        g = providers.GigaChat()
        sent = []

        async def fake_complete(system, user, temperature, max_tokens):
            sent.append(providers._MODEL.get() or g.model)
            return "{}", {}

        g._complete = fake_complete
        view = providers.for_task(g, "plan")
        assert view is not g and view.model == "GigaChat-2-Max" and providers.for_task(g, "dossier") is g
        res = asyncio.run(view.complete("s", "u"))
        asyncio.run(g.complete("s", "u"))
        assert sent == ["GigaChat-2-Max", "GigaChat-2"] and res.model == "GigaChat-2-Max"
        assert providers.llm_label() == "gigachat:GigaChat-2 (план поиска: GigaChat-2-Max)"
    finally:
        get_settings.cache_clear()


@pytest.mark.parametrize("q, prof", [
    ("микрофлюидные технологии", "life_med"), ("технологии многослойного графена", "materials"), ("CRISPR-диагностика", "life_med"),
    ("твердотельные аккумуляторы", "energy"), ("перспективные решения в финтехе", "software"), ("газлифт", "energy"),
])
def test_routing_profiles(q, prof):
    r = routing.route(q)
    assert r["profile"] == prof
    assert r["ml_evidence"] == routing.is_ai(q)  # HF Papers и OpenReview по кандидату — только для запросов про ИИ
    assert r["europepmc_corpus"] == (prof != "software")


def test_nsf_prefixes_and_sbir():
    assert strip_program_prefix("Collaborative Research: DMREF: Catalyst Surfaces") == ("Catalyst Surfaces", False)
    assert strip_program_prefix("SBIR Phase I: Low-cost microfluidic assay") == ("Low-cost microfluidic assay", True)
    assert strip_program_prefix("Graphene: a new route") == ("Graphene: a new route", False)


def test_card_facts_hide_imputed_age():
    f = {"age_years": 20.0}
    assert card_facts(f, {}, None, 2026)["first_year"] == 2006
    assert card_facts(f, {}, None, 2026, ["openalex"])["first_year"] is None


def test_decide_module_exports_formula():
    assert decide_mod.P_CAP == 0.95
