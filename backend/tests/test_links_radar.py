"""Проверка ссылок источников, радар технологий банка, ряд публикаций по годам."""
import asyncio

import httpx
import pytest

from app.pipeline import links
from app.pipeline import passport as pp


def _check(handler, urls):
    return asyncio.run(links.check_all(urls, transport=httpx.MockTransport(handler)))


def test_link_statuses():
    def handler(r):
        path = r.url.path
        if path == "/ok":
            return httpx.Response(200)
        if path == "/gone":
            return httpx.Response(404)
        if path == "/removed":
            return httpx.Response(410)
        if path == "/blocked":
            return httpx.Response(403)
        if path == "/nohead":
            return httpx.Response(405) if r.method == "HEAD" else httpx.Response(200)
        if path == "/down":
            raise httpx.ConnectError("no route", request=r)
        if path == "/slow":
            raise httpx.ReadTimeout("slow", request=r)
        if path == "/redirect":
            return httpx.Response(301, headers={"location": "https://site.test/ok"})
        return httpx.Response(500)

    base = "https://site.test"
    res = _check(handler, [f"{base}/{p}" for p in ("ok", "gone", "removed", "blocked", "nohead", "down", "slow", "redirect", "error")] + ["ftp://x", ""])
    assert res[f"{base}/ok"] == "ok" and res[f"{base}/redirect"] == "ok" and res[f"{base}/nohead"] == "ok"
    assert res[f"{base}/gone"] == res[f"{base}/removed"] == res[f"{base}/down"] == "dead"
    # Сайт запрещает робота или долго отвечает — не утверждаем, что ссылка битая.
    assert res[f"{base}/blocked"] == res[f"{base}/slow"] == res[f"{base}/error"] == "restricted"
    assert res["ftp://x"] == "dead" and "" not in res


def test_duplicate_links_checked_once():
    calls = []

    def handler(r):
        calls.append(str(r.url))
        return httpx.Response(200)

    res = _check(handler, ["https://a.test/1", "https://a.test/1", "https://a.test/2"])
    assert len(res) == 2 and len(calls) == 2


@pytest.mark.parametrize("text, area", [
    ("Agent payments protocol for instant settlement", "Платежи и переводы"),
    ("Tokenized deposits on a distributed ledger, stablecoin settlement", "Цифровые активы и токенизация"),
    ("Alternative data credit scoring for SME lending", "Кредитование и скоринг"),
    ("Deepfake liveness attacks on remote onboarding fraud", "Антифрод и ПОД/ФТ"),
    ("Reusable zero-knowledge KYC credentials and regtech compliance", "Комплаенс и KYC"),
    ("Prompt injection attacks on LLM agents: security", "Кибербезопасность"),
    ("Disaggregated GPU inference in the data center", "ИТ-инфраструктура и данные"),
    ("Voice assistants for customer service", "Клиентский сервис и каналы"),
    ("LLM trading agents for portfolio management", "Инвестиции и казначейство"),
    ("Autonomous warehouse robots", pp.OUTSIDE),
])
def test_bank_area(text, area):
    assert pp.bank_area(text) == area


def test_ai_security_is_cybersecurity():
    for name in ("Градиенто-зависимые адверсариальные атаки", "Прототипирование red-teaming benchmarks", "Secure Aggregation", "Backdoor attacks on LLM agents"):
        assert pp.bank_area("", name) == "Кибербезопасность", name


@pytest.mark.parametrize("name, titles", [
    ("Segment Anything Model SAM", "Accelerating vision foundation model for efficient medical image segmentation. Regulating the nano-bio interface"),
    ("editing in plants", "AI and multiplex gene editing: identity of plant traits"),
    ("wearable biosensors", "Sweat-based wearable biosensors for personalized health monitoring agents"),
])
def test_no_random_bank_area_for_non_banking_tech(name, titles):
    # Случайные слова в заголовках («regulating», «identity», «agents») не делают технологию банковской.
    assert pp.bank_area(titles, name) == pp.OUTSIDE


def test_bank_radar_rings_and_horizon():
    strong = {"level": "A", "hard_event": True, "event_level": 6}
    medium = {"level": "B", "hard_event": False, "event_level": 2}
    weak = {"level": "C", "hard_event": False, "event_level": 1}
    r = pp.bank_radar("Agent payments", [], {}, strong, "signal")
    assert (r["ring"], r["horizon"], r["area"], r["by"]) == ("Пилотировать", "до 2 лет", "Платежи и переводы", "rules")
    assert pp.bank_radar("x", [], {}, medium, "signal")["ring"] == "Изучать" and pp.bank_radar("x", [], {}, medium, "signal")["horizon"] == "2–5 лет"
    assert pp.bank_radar("x", [], {}, weak, "watch")["ring"] == "Наблюдать" and pp.bank_radar("x", [], {}, weak, "watch")["horizon"] == "5 лет и более"
    # Выбор GigaChat принимается только при совпадении с правилами (реальный случай 17.10: микророботы → «KYC»).
    robots = pp.bank_radar("Magnetically Controlled Microrobots", [{"title": "Ferrofluid microrobots for tumor therapy"}], {"bank_area": "Комплаенс и KYC"}, medium, "signal")
    assert robots["area"] == pp.OUTSIDE and robots["llm_area"] == "Комплаенс и KYC" and robots["by"] == "rules"
    agreed = pp.bank_radar("Agent payments", [], {"bank_area": "Платежи и переводы"}, medium, "signal")
    assert agreed["area"] == "Платежи и переводы" and agreed["by"] == "rules+gigachat" and agreed["llm_area"] is None


def test_llm_bank_areas_match_rules():
    from app.llm.tasks import BANK_AREA_NAMES

    assert BANK_AREA_NAMES == [a for a, _ in pp.BANK_AREAS] + [pp.OUTSIDE]


@pytest.mark.parametrize("a, b, dup", [
    ("in-orbit servicing", "on-orbit servicing", True),
    ("Tokenized deposits", "tokenized deposit", True),
    ("LLM trading agents", "LLM trading agent benchmark", True),
    ("quantum sensing", "quantum computing", False),
    ("edge AI", "edge inference accelerator", False),
])
def test_near_duplicates(a, b, dup):
    from app.pipeline.decide import near_duplicate

    assert near_duplicate(a, b) is dup


def test_organizations_and_synonyms_do_not_take_top_places():
    import math

    from app.collectors.base import RawDoc
    from app.decision.base import DecisionResult
    from app.ml.model import SignalModel
    from app.pipeline.decide import decide
    from app.pipeline.evidence import Evidence
    from app.pipeline.features import FEATURES

    model = SignalModel(features=list(FEATURES), mean=[0.0] * len(FEATURES), scale=[1.0] * len(FEATURES), coef=[0.1] * len(FEATURES), intercept=0.0, meta={})
    ans = {"relevance": 0.9, "specific_tech": 0.9, "standard": 0.1, "mass_adoption": 0.1, "market_leaders": 0.1, "hype": 0.1}

    def item(name, p):
        ev = Evidence(name, docs=[RawDoc(url=f"https://arxiv.org/abs/{name}{i}", title="t", source_type="preprint") for i in range(5)])
        res = DecisionResult({k: {"type": "noul", "value": v} for k, v in ans.items()}, "t", "t", 0)
        return {"c": {"name_en": name}, "ev": ev, "items": [], "res": res, "features": {"log_total_works": math.log1p(50)}, "prob": p}

    items = [item("on-orbit servicing", 0.9), item("in-orbit servicing", 0.8), item("US Federal Communications Commission", 0.95), item("direct-to-device satellites", 0.7)]
    out = decide(items, model, top_k=15)
    st = {i["c"]["name_en"]: (d["status"], d.get("code")) for i, d in zip(items, out, strict=True)}
    assert st["on-orbit servicing"] == ("signal", None) and st["in-orbit servicing"] == ("excluded", "duplicate")
    assert st["US Federal Communications Commission"] == ("excluded", "organization")
    assert [d.get("rank") for d in out if d["status"] == "signal"] == [1, 2]


def test_dynamics_series():
    d = pp.dynamics({"2020": 1, 2025: 12, 2026: 30}, 2026, years=4)
    assert d == [{"year": 2023, "works": 0, "partial": False}, {"year": 2024, "works": 0, "partial": False},
                 {"year": 2025, "works": 12, "partial": False}, {"year": 2026, "works": 30, "partial": True}]
