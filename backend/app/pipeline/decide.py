"""Итоговое решение по кандидату: слабый сигнал или исключение с понятной причиной.

Порядок: сначала явные фильтры (нерелевантно, слишком общее, стандарт, зрелое, хайп,
мало подтверждений), затем вероятность классификатора и ранжирование.
Пороги фильтров зафиксированы в коде и описаны в методологии.
"""
import math
import re

from app.ml.model import SignalModel
from app.pipeline.passport import prob_text
from app.pipeline.trust import classify

EXCLUSION_RU = {
    "irrelevant": "Нерелевантно запросу",
    "broad": "Слишком общее направление",
    "product": "Отдельный продукт или компания",
    "not_technology": "Не инновация (документ, явление, организация)",
    "standard": "Отраслевой стандарт",
    "mature": "Зрелая технология / сформированный рынок",
    "hype": "Маркетинговый шум",
    "low_evidence": "Недостаточно подтверждений",
    "low_trust": "Только источники с пониженным доверием",
    "low_probability": "Низкая вероятность слабого сигнала",
    "reserve": "Не вошёл в топ по итоговому баллу",
    "no_decision": "Не проверен: decision-модель недоступна",
    "watch": "Наблюдать: мало подтверждённых документов",
    "organization": "Организация, а не технология",
    "duplicate": "Повтор: синоним технологии выше в списке",
    "paper_title": "Название статьи, а не технологии",
    "crowded": "Тема уже представлена в топе",
}

# Формулировки научных статей, а не технологий: «Stackelberg Model of AI Security», «Stablecoin under stress».
PAPER_TITLE = re.compile(
    r"\b(model|characteri[sz]ation|manipulation|analysis|study|survey|review|evaluation|investigation|assessment|case|role|impact|"
    r"perspective|overview|comparison|understanding) of\b|\bunder (stress|attack|uncertainty)\b|\b(towards?|a|an|the)\b \w+ \w+",
    re.I,
)
# Слова, по которым темы не считаются «одинаковыми» при проверке разнообразия топа.
_GENERIC_WORDS = {"ai", "learning", "neural", "network", "model", "data", "system", "based", "deep", "machine", "intelligent",
                  "computing", "detection", "control", "optimization", "edge", "llm", "agent", "security", "robot", "robotic", "digital",
                  "smart", "adaptive", "hybrid", "real", "time", "multi", "self", "generative", "large", "language", "federated"}
MAX_PER_THEME = 3

# Названия организаций, а не технологий (работает и без decision-модели).
ORG = re.compile(
    r"\b(commission|agency|association|consortium|ministry|department|administration|authority|university|institute|foundation|"
    r"inc|ltd|llc|corp|corporation|gmbh|plc|bank of|federal reserve)\b|министерств|комисси|ассоциаци|агентств|университет|институт|корпораци",
    re.I,
)
# Слова-связки для сравнения названий: «in-orbit servicing» и «on-orbit servicing» — одно и то же.
_LINK_WORDS = {"in", "on", "of", "for", "the", "and", "a", "an", "based", "driven", "enabled"}


def _key_words(name: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]+", name.lower().replace("-", " "))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if w not in _LINK_WORDS}


def near_duplicate(a: str, b: str) -> bool:
    wa, wb = _key_words(a), _key_words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= 0.6


def _ans(a: dict, key: str, default: float = 0.5) -> float:
    return float((a["res"].answers.get(key) or {}).get("value", default))


def relevance(a: dict) -> float:
    """Кандидат должен подходить и к теме плана, и к исходной формулировке запроса — берём меньшую оценку."""
    return min(_ans(a, "relevance", 0.6), _ans(a, "relevance_query", 1.0))


def _filters(a: dict) -> tuple[str, str] | None:
    f = a["features"]
    if not a["res"].ok:
        return "no_decision", "Decision-модель не ответила (сбой сети) — признаки не проверены, кандидат не ранжируется."
    rel = relevance(a)
    if rel < 0.34:
        return "irrelevant", f"Слабо связано с запросом (оценка релевантности {rel:.2f} из 1: к теме {_ans(a, 'relevance', 0.6):.2f}, к исходной формулировке {_ans(a, 'relevance_query', 1.0):.2f})."
    if _ans(a, "evidence_match", 1.0) < 0.4:
        return "low_evidence", f"Найденные источники не обсуждают эту технологию напрямую (оценка соответствия {_ans(a, 'evidence_match', 1.0):.0%}) — вероятно, это случайное сочетание слов."
    if ORG.search(a["c"]["name_en"]):
        return "organization", "Название организации (комиссия, агентство, университет, компания), а не технологии."
    if PAPER_TITLE.search(a["c"]["name_en"]) or len(a["c"]["name_en"].split()) > 7:
        return "paper_title", "Формулировка похожа на заголовок научной статьи, а не на название класса технологий — такой кандидат нельзя проверить поиском по источникам."
    if _ans(a, "is_technology", 1.0) < 0.3:
        return "not_technology", f"Это не технологическая инновация, а документ, репозиторий, организация или общее рыночное явление (оценка {_ans(a, 'is_technology', 1.0):.0%})."
    if _ans(a, "product_name", 0.0) >= 0.6:
        return "product", f"Это название конкретного продукта, компании или проекта (оценка {_ans(a, 'product_name', 0.0):.0%}), а не класс технологий."
    if _ans(a, "specific_tech") < 0.25:
        return "broad", "Это широкая область или общее понятие, а не конкретная технология — такие направления не являются слабыми сигналами."
    if _ans(a, "standard") >= 0.6:
        return "standard", f"Decision-модель оценивает вероятность того, что это действующий стандарт или протокол, в {_ans(a, 'standard'):.0%}."
    works = math.expm1(f.get("log_total_works", 0))
    views = math.expm1(f.get("log_wiki_views", 0))
    mature_reasons = []
    if _ans(a, "mass_adoption") >= 0.6:
        mature_reasons.append(f"признаки массового внедрения ({_ans(a, 'mass_adoption'):.0%})")
    if _ans(a, "market_leaders") >= 0.65:
        mature_reasons.append(f"сформированный рынок с лидерами ({_ans(a, 'market_leaders'):.0%})")
    if "wikipedia" not in a.get("missing", []) and f.get("wiki_exists") and views > 5000 and f.get("age_years", 0) >= 8:
        mature_reasons.append(f"устоявшаяся статья в Википедии (~{views:,.0f} просмотров в месяц) и {f['age_years']:.0f} лет в литературе".replace(",", " "))
    if works > 20000:
        mature_reasons.append(f"более {works:,.0f} научных работ".replace(",", " "))
    if mature_reasons:
        return "mature", "Зрелая технология: " + "; ".join(mature_reasons) + "."
    if _ans(a, "hype") >= 0.75 and f.get("share_science", 0) < 0.2:
        return "hype", f"Доказательства состоят в основном из рекламных материалов (оценка шума {_ans(a, 'hype'):.0%}), научных подтверждений мало."
    docs = a["ev"].docs
    if len(docs) < 3:
        return "low_evidence", f"В открытых источниках найдено только {len(docs)} подтверждения — недостаточно для вывода."
    trusted = [d for d in docs if classify(d)[1] in ("high", "medium")]
    if not trusted:
        return "low_trust", "Все найденные упоминания — блоги, соцсети или пресс-релизы; независимого подтверждения нет."
    return None


def decide(assessed: list[dict], model: SignalModel | None, top_k: int) -> list[dict]:
    out: list[dict] = []
    for a in assessed:
        contrib = model.explain(a["features"]) if model else []
        rel = relevance(a)
        d = {"relevance": rel, "contributions": contrib}
        flt = _filters(a)
        pp = a.get("passport")
        if flt:
            d.update(status="excluded", code=flt[0], reason=flt[1])
        elif a["prob"] is not None and a["prob"] < 0.5:
            neg = [c for c in contrib if c["contribution"] < 0][:3]
            why = "; ".join(f"{c['label'].lower()} — {c.get('level', '')} значение ({c['value']})" for c in neg)
            d.update(status="excluded", code="low_probability", reason=f"Модель оценивает вероятность слабого сигнала в {a['prob']:.0%}. Основные факторы против: {why}.")
        elif pp and pp["level"] == "C":
            # Турникет: без подтверждённых документов высокая вероятность ничего не значит — признаки
            # считались по пустым или чужим текстам. Кандидат не попадает в топ, а уходит в «Наблюдать».
            d.update(
                status="watch", code="watch",
                reason=f"Decision-модель подтвердила {pp['confirmed']} из {pp['checked']} документов ({pp['domains']} разных источника) — "
                       "этого мало для вывода. Вероятность модели без доказательств не учитывается.",
            )
        else:
            d.update(status="signal")
        out.append(d)

    ranked = sorted(
        [i for i, d in enumerate(out) if d["status"] == "signal"],
        key=lambda i: -((assessed[i]["prob"] or 0.5) * (0.6 + 0.4 * out[i]["relevance"])),
    )
    # Синонимы не занимают два места в топе: остаётся вариант с более высоким баллом.
    # Разнообразие: одна узкая тема (например, «quantum») — не больше MAX_PER_THEME мест, иначе топ по
    # «инфраструктуре для ИИ» превращается в список вариантов квантового машинного обучения.
    kept: list[int] = []
    themes: dict[str, int] = {}
    for i in ranked:
        name = assessed[i]["c"]["name_en"]
        twin = next((k for k in kept if near_duplicate(name, assessed[k]["c"]["name_en"])), None)
        theme = next((w for w in sorted(_key_words(name) - _GENERIC_WORDS) if len(w) > 3 and themes.get(w, 0) >= MAX_PER_THEME), None)
        if twin is not None:
            out[i].update(status="excluded", code="duplicate", reason=f"Синоним технологии «{assessed[twin]['c']['name_en']}», которая уже в списке.")
        elif theme and len(kept) < top_k:
            out[i].update(status="excluded", code="crowded", reason=f"В топе уже {MAX_PER_THEME} технологии на тему «{theme}» — место отдано другим направлениям.")
        else:
            kept.append(i)
            for w in _key_words(name) - _GENERIC_WORDS:
                themes[w] = themes.get(w, 0) + 1
    ranked = kept
    for r, i in enumerate(ranked):
        if r < top_k:
            out[i]["rank"] = r + 1
        else:
            out[i].update(status="excluded", code="reserve", reason="Прошёл фильтры, но не вошёл в топ по итоговому баллу (вероятность × релевантность).")
    return out


def wiki_fact(f: dict, missing: list[str]) -> str:
    if "wikipedia" in missing:
        return "Данные Википедии недоступны"
    return "Статья в англоязычной Википедии есть" if f.get("wiki_exists") else "Статьи в англоязычной Википедии нет"


def template_dossier(a: dict, d: dict) -> dict:
    """Досье без LLM: собирается из признаков и заголовков источников (всегда доступно)."""
    f = a["features"]
    works = int(round(math.expm1(f.get("log_total_works", 0))))
    parts = []
    if works:
        parts.append(f"в научной литературе найдено около {works} работ, из них {f.get('recent_share', 0):.0%} — за последние 3 года")
    if f.get("age_years"):
        parts.append(f"тема заметна в публикациях около {f['age_years']:.0f} лет")
    parts.append(wiki_fact(f, a.get("missing", [])).lower())
    if f.get("log_gh_repos_12m"):
        parts.append(f"за 12 месяцев создано ~{int(math.expm1(f['log_gh_repos_12m']))} репозиториев GitHub")
    stage = a["res"].answers.get("maturity", {}).get("value")
    contrib = d.get("contributions", [])
    pos = [f"{c['label']} — {c.get('level', '')} значение" for c in contrib if c["contribution"] > 0][:3]
    neg = [f"{c['label']} — {c.get('level', '')} значение" for c in contrib if c["contribution"] < 0][:2]
    conf = ""
    if a["prob"] is not None:
        conf = f"Вероятность слабого сигнала по модели {prob_text(a['prob'])}. Сильнее всего «за»: {', '.join(pos) or '—'}. «Против»: {', '.join(neg) or '—'}."
        pp = a.get("passport")
        if pp:
            conf += f" Паспорт доказательств {pp['level']}: подтверждено {pp['confirmed']} из {pp['checked']} документов, {pp['domains']} разных источника."
        if "openalex" in a.get("missing", []):
            conf += " Внимание: статистика публикаций OpenAlex была недоступна, признаки публикаций заменены нейтральными значениями."
        if "wikipedia" in a.get("missing", []):
            conf += " Внимание: Википедия была недоступна, признаки известности заменены нейтральными значениями."
    first = a["items"][0] if a["items"] else None
    return {
        "description": f"«{a['c']['name_en']}» — технология, выявленная в документах по запросу. Подробное описание формируется LLM по найденным источникам.",
        "why_weak_signal": "По наблюдаемым показателям: " + "; ".join(parts) + "."
        + (f" Decision-модель оценивает зрелость на {stage:.2f} по шкале 0 (исследование) — 1 (мейнстрим)." if stage is not None else ""),
        "confidence_explanation": conf,
        "case_example": f"См. источник: {first['title']} ({first['source']}, {first.get('date') or 'без даты'})." if first else "",
        "generated_by": "template",
    }
