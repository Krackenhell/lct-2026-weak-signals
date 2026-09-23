"""Итоговое решение по кандидату: слабый сигнал или исключение с понятной причиной.

Порядок: сначала явные фильтры (нерелевантно, слишком общее, стандарт, зрелое, хайп,
мало подтверждений), затем вероятность классификатора и ранжирование.
Пороги фильтров зафиксированы в коде и описаны в методологии.
"""
import math

from app.ml.model import SignalModel
from app.pipeline.trust import classify

EXCLUSION_RU = {
    "irrelevant": "Нерелевантно запросу",
    "broad": "Слишком общее направление",
    "product": "Отдельный продукт или компания",
    "not_technology": "Не технология",
    "standard": "Отраслевой стандарт",
    "mature": "Зрелая технология / сформированный рынок",
    "hype": "Маркетинговый шум",
    "low_evidence": "Недостаточно подтверждений",
    "low_trust": "Только источники с пониженным доверием",
    "low_probability": "Низкая вероятность слабого сигнала",
    "reserve": "Не вошёл в топ по итоговому баллу",
}


def _ans(a: dict, key: str, default: float = 0.5) -> float:
    return float((a["res"].answers.get(key) or {}).get("value", default))


def _filters(a: dict) -> tuple[str, str] | None:
    f = a["features"]
    rel = _ans(a, "relevance", 0.6)
    if rel < 0.34:
        return "irrelevant", f"Слабо связано с темой запроса (оценка релевантности {rel:.2f} из 1)."
    if _ans(a, "evidence_match", 1.0) < 0.4:
        return "low_evidence", f"Найденные источники не обсуждают эту технологию напрямую (оценка соответствия {_ans(a, 'evidence_match', 1.0):.0%}) — вероятно, это случайное сочетание слов."
    if _ans(a, "is_technology", 1.0) < 0.5:
        return "not_technology", f"Это не технология, а документ, явление, организация или тема политики (оценка «это технология» {_ans(a, 'is_technology', 1.0):.0%})."
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
    if f.get("wiki_exists") and views > 5000 and f.get("age_years", 0) >= 8:
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
        rel = _ans(a, "relevance", 0.6)
        d = {"relevance": rel, "contributions": contrib}
        flt = _filters(a)
        if flt:
            d.update(status="excluded", code=flt[0], reason=flt[1])
        elif a["prob"] is not None and a["prob"] < 0.5:
            neg = [c for c in contrib if c["contribution"] < 0][:3]
            why = "; ".join(f"{c['label'].lower()} — {c.get('level', '')} значение ({c['value']})" for c in neg)
            d.update(status="excluded", code="low_probability", reason=f"Модель оценивает вероятность слабого сигнала в {a['prob']:.0%}. Основные факторы против: {why}.")
        else:
            d.update(status="signal")
        out.append(d)

    ranked = sorted(
        [i for i, d in enumerate(out) if d["status"] == "signal"],
        key=lambda i: -((assessed[i]["prob"] or 0.5) * (0.6 + 0.4 * out[i]["relevance"])),
    )
    for r, i in enumerate(ranked):
        if r < top_k:
            out[i]["rank"] = r + 1
        else:
            out[i].update(status="excluded", code="reserve", reason="Прошёл фильтры, но не вошёл в топ по итоговому баллу (вероятность × релевантность).")
    return out


def template_dossier(a: dict, d: dict) -> dict:
    """Досье без LLM: собирается из признаков и заголовков источников (всегда доступно)."""
    f = a["features"]
    works = int(round(math.expm1(f.get("log_total_works", 0))))
    parts = []
    if works:
        parts.append(f"в научной литературе найдено около {works} работ, из них {f.get('recent_share', 0):.0%} — за последние 3 года")
    if f.get("age_years"):
        parts.append(f"тема заметна в публикациях около {f['age_years']:.0f} лет")
    parts.append("статьи в англоязычной Википедии нет" if not f.get("wiki_exists") else "есть статья в Википедии")
    if f.get("log_gh_repos_12m"):
        parts.append(f"за 12 месяцев создано ~{int(math.expm1(f['log_gh_repos_12m']))} репозиториев GitHub")
    stage = a["res"].answers.get("maturity", {}).get("value")
    contrib = d.get("contributions", [])
    pos = [f"{c['label']} — {c.get('level', '')} значение" for c in contrib if c["contribution"] > 0][:3]
    neg = [f"{c['label']} — {c.get('level', '')} значение" for c in contrib if c["contribution"] < 0][:2]
    conf = ""
    if a["prob"] is not None:
        conf = f"Уверенность модели {a['prob']:.0%}. Сильнее всего «за»: {', '.join(pos) or '—'}. «Против»: {', '.join(neg) or '—'}."
    first = a["items"][0] if a["items"] else None
    return {
        "description": f"«{a['c']['name_en']}» — технология, выявленная в документах по запросу. Подробное описание формируется LLM по найденным источникам.",
        "why_weak_signal": "По наблюдаемым показателям: " + "; ".join(parts) + "."
        + (f" Decision-модель оценивает зрелость на {stage:.2f} по шкале 0 (исследование) — 1 (мейнстрим)." if stage is not None else ""),
        "confidence_explanation": conf,
        "case_example": f"См. источник: {first['title']} ({first['source']}, {first.get('date') or 'без даты'})." if first else "",
        "generated_by": "template",
    }
