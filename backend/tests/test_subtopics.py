"""Растущие поднаправления темы: ключевой термин, рост и специфичность ключевых слов, сама тема не сигнал."""
import asyncio

import httpx
import pytest

from app.llm.tasks import clean_phrase
from app.pipeline import subtopics
from app.pipeline.decide import is_topic_itself
from tests.fakes import FakeWeb


@pytest.mark.parametrize("raw, expected", [
    ("smart_wellhead_monitoring", "smart wellhead monitoring"),  # реальный ответ GigaChat на «нефтегазовое дело»
    ("oil-and-gas-technology", "oil and gas technology"),
    ("«zero-knowledge KYC»", "zero knowledge KYC"),
])
def test_clean_phrase(raw, expected):
    assert clean_phrase(raw) == expected


@pytest.mark.parametrize("topic, core", [
    ("microfluidics technologies", "microfluidics"),
    ("emerging multilayer graphene technologies", "multilayer graphene"),
    ("oil-and-gas-technology", "oil and gas"),
])
def test_core_term(topic, core):
    assert subtopics.core_term(topic) == core


def test_long_phrase_is_shortened_to_searchable_core():
    assert subtopics._shorter("gas lift in gas condensate wells") == ["gas lift in gas condensate wells", "gas lift"]


def _openalex(handler):
    h = FakeWeb().client()
    h._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return h


def test_emerging_keeps_growing_and_specific_keywords():
    recent = {"rhombohedral graphene": 18, "chiral superconductivity": 17, "raman spectroscopy": 11, "corrosion resistance": 13,
              "graphene": 300, "multilayer graphene devices": 9, "electron transport": 40}
    prior = {"electron transport": 60, "raman spectroscopy": 2}
    totals = {"rhombohedral-graphene": 128, "chiral-superconductivity": 102, "corrosion-resistance": 17095, "electron-transport": 900}

    def handler(r):
        p = r.url.params
        if "group_by" in p:
            src = recent if p["filter"].endswith(f"publication_year:{subtopics.date.today().year - 1}-{subtopics.date.today().year}") else prior
            return httpx.Response(200, json={"group_by": [{"key": f"https://openalex.org/keywords/{k.replace(' ', '-')}", "key_display_name": k, "count": n}
                                                          for k, n in src.items()]})
        kid = p["filter"].split("keywords.id:")[1].split(",")[0]
        return httpx.Response(200, json={"meta": {"count": totals.get(kid, 0)}, "results": []})

    found = asyncio.run(subtopics.emerging(_openalex(handler), "multilayer graphene"))
    names = [f["keyword"] for f in found]
    assert names[:2] == ["rhombohedral graphene", "chiral superconductivity"]
    assert "corrosion resistance" not in names  # растёт, но не специфично для темы (тема — 0,08% его работ)
    assert "raman spectroscopy" not in names  # общий метод из списка неинформативных
    assert "multilayer graphene devices" not in names  # это сама тема с общим словом
    assert "electron transport" not in names  # доля упала
    assert found[0]["specificity"] == round(18 / 128, 3)


def test_literature_candidates_point_to_corpus_docs():
    from app.collectors.base import RawDoc
    corpus = [RawDoc(url="u1", title="Chiral superconductivity in rhombohedral graphene"), RawDoc(url="u2", title="Other")]
    c = subtopics.literature_candidates([{"keyword": "rhombohedral graphene", "growth": 1.6}], corpus)[0]
    assert c["method"] == "literature-growth" and c["doc_idx"] == [0]


@pytest.mark.parametrize("name, itself", [
    ("multilayer graphene", True),
    ("multilayer graphene technologies", True),
    ("Multilayer Graphene Devices", True),
    ("rhombohedral multilayer graphene", False),
    ("bilayer graphene quantum dots", False),
])
def test_topic_itself_is_not_a_signal(name, itself):
    assert is_topic_itself(name, ["multilayer graphene", "multilayer graphene technologies"]) is itself


def _cand(name, p=0.9, level="B", evidence_match=0.9):
    from types import SimpleNamespace

    from app.collectors.base import RawDoc

    answers = {k: {"value": v} for k, v in {"relevance": 0.9, "specific_tech": 0.9, "is_technology": 0.9, "evidence_match": evidence_match}.items()}
    ev = SimpleNamespace(docs=[RawDoc(url=f"https://arxiv.org/abs/{name}{i}", title="t", source_name="arXiv", source_type="preprint", collector="arxiv")
                               for i in range(4)])
    return {"c": {"name_en": name}, "res": SimpleNamespace(ok=True, answers=answers), "features": {}, "prob": p, "ev": ev, "passport": {"level": level}}


def test_document_level_check_overrides_strict_overall_match():
    from app.pipeline.decide import decide

    # «rhombohedral graphene»: общий вопрос 0,38, но Jev подтвердил 10 из 10 документов (паспорт B) — это сигнал.
    out = decide([_cand("rhombohedral graphene", evidence_match=0.38, level="B"),
                  _cand("random phrase", evidence_match=0.2, level="C")], None, 15)
    assert out[0]["status"] == "signal"
    assert out[1]["code"] == "low_evidence"  # и общий вопрос, и паспорт против — отсев остаётся


def test_topic_words_do_not_count_as_crowded_theme():
    from app.pipeline.decide import decide

    names = ["rhombohedral graphene", "bilayer graphene quantum dots", "graphene plasmonics", "twisted graphene superlattices", "graphene membranes"]
    out = decide([_cand(n, 0.99 - i / 100) for i, n in enumerate(names)], None, 15, topic_terms=["multilayer graphene"])
    assert all(d["status"] == "signal" for d in out)  # «graphene» — слово темы запроса, а не повторяющаяся тема
    out = decide([_cand(n, 0.99 - i / 100) for i, n in enumerate(names)], None, 15)
    assert sum(d.get("code") == "crowded" for d in out) == 2  # без темы запроса — прежнее ограничение 3 на тему


def test_near_duplicate_uses_word_stems():
    from app.pipeline.decide import near_duplicate

    assert near_duplicate("chiral superconductivity", "chiral superconductors")  # реальный дубль в топе 19.10
    assert not near_duplicate("fractional chern insulator", "chern insulator in graphene")
    assert not near_duplicate("graphene plasmonics", "graphene photonics")


def test_clean_name_drops_paper_tail():
    from app.pipeline.discovery import clean_name

    assert clean_name("Yb-doped ZnO investigation") == "Yb-doped ZnO"


def test_meta_wrappers_removed_from_topic():
    """План GigaChat переносил «Early Signals in …» из запроса в тему — поиск по литературе шёл по словам «early signals» (20.10)."""
    from app.pipeline.subtopics import clean_topic

    assert clean_topic("Early Signals in AI Cybersecurity") == "AI Cybersecurity"
    assert clean_topic("Early stage Robotics") == "Robotics"
    assert clean_topic("Early Technological Signals in FinTech") == "FinTech"
    assert clean_topic("Early detection of cancer") == "Early detection of cancer"  # смысловое «early» остаётся
    assert clean_topic("multilayer graphene") == "multilayer graphene"
