"""Признаки слабого сигнала. Две группы:

1. Наблюдаемые количественные (библиометрия, активность разработчиков, массовая известность).
2. Ответы decision-модели на атомарные вопросы по тексту доказательств.

Все признаки имеют понятный смысл — это требование интерпретируемости из ТЗ.
"""
import math
from datetime import date

from app.pipeline.evidence import Evidence

NUMERIC = [
    "log_total_works",
    "recent_share",
    "growth",
    "age_years",
    "wiki_exists",
    "log_wiki_views",
    "log_gh_repos_12m",
    "log_hn_12m",
    "fresh_preprints",
    "share_science",
    "log_evidence",
]
ANSWERS = ["specific_tech", "mass_adoption", "market_leaders", "standard", "early_stage", "independent", "hype", "novelty", "benefit", "maturity"]
FEATURES = NUMERIC + ANSWERS
CORE_COLLECTORS = ("arxiv", "hackernews")

FEATURE_RU = {
    "log_total_works": "Объём научных публикаций за всё время (лог)",
    "recent_share": "Доля публикаций за последние 3 года",
    "growth": "Рост публикаций: последние 2 года к предыдущим 2",
    "age_years": "Возраст темы в литературе, лет",
    "wiki_exists": "Есть статья в Википедии",
    "log_wiki_views": "Просмотры статьи в Википедии в месяц (лог)",
    "log_gh_repos_12m": "Новые репозитории GitHub за 12 мес (лог)",
    "log_hn_12m": "Обсуждения в инженерном сообществе за 12 мес (лог)",
    "fresh_preprints": "Доля препринтов arXiv за последние 12 мес",
    "share_science": "Доля научных источников в доказательствах",
    "log_evidence": "Число найденных подтверждений (лог)",
    "specific_tech": "Конкретная технология (decision-модель)",
    "mass_adoption": "Массовое внедрение (decision-модель)",
    "market_leaders": "Сформированный рынок с лидерами (decision-модель)",
    "standard": "Действующий стандарт (decision-модель)",
    "early_stage": "Ранняя стадия (decision-модель)",
    "independent": "Независимые участники (decision-модель)",
    "hype": "Маркетинговый шум (decision-модель)",
    "novelty": "Новизна (decision-модель)",
    "benefit": "Конкретное преимущество (decision-модель)",
    "maturity": "Уровень зрелости (decision-модель)",
}


def numeric_features(ev: Evidence) -> dict[str, float]:
    today = date.fromisoformat(ev.today) if ev.today else date.today()
    y = today.year
    frac = max(today.timetuple().tm_yday / 365.0, 0.25)
    c = ev.yearly or {}
    total = sum(v for k, v in c.items() if k <= y)
    recent3 = c.get(y, 0) + c.get(y - 1, 0) + c.get(y - 2, 0)
    recent = (c.get(y, 0) / frac + c.get(y - 1, 0)) / 2
    prior = (c.get(y - 2, 0) + c.get(y - 3, 0)) / 2
    first = next((k for k in sorted(c) if c[k] >= 3 and k <= y), None)

    # Признаки считаются только по «ядровым» источникам, которые собираются одинаково
    # при обучении и при живом поиске (иначе распределения признаков разойдутся).
    docs = [d for d in ev.docs if d.collector in CORE_COLLECTORS]
    n = len(docs)
    arx = [d for d in docs if d.collector == "arxiv"]
    cutoff = date(y - 1, today.month, min(today.day, 28)).isoformat()
    fresh = sum(1 for d in arx if (d.published or "") >= cutoff)
    sci = sum(1 for d in docs if d.source_type in ("science", "preprint"))

    return {
        "log_total_works": math.log1p(total),
        "recent_share": recent3 / total if total else 0.0,
        "growth": math.log1p(recent) - math.log1p(prior),
        "age_years": float(min(y - first, 40)) if first else 0.0,
        "wiki_exists": 1.0 if ev.wiki.get("exists") else 0.0,
        "log_wiki_views": math.log1p(ev.wiki.get("monthly_views", 0.0) or 0.0),
        "log_gh_repos_12m": math.log1p(ev.gh_repos_12m or 0),
        "log_hn_12m": math.log1p(ev.hn_12m or 0),
        "fresh_preprints": fresh / 15.0,
        "share_science": sci / n if n else 0.0,
        "log_evidence": math.log1p(n),
    }


def answer_features(answers: dict) -> dict[str, float]:
    out = {}
    for k in ANSWERS:
        a = answers.get(k) or {}
        out[k] = float(a.get("value", 0.5))
    return out


def all_features(ev: Evidence, answers: dict) -> dict[str, float]:
    return {**numeric_features(ev), **answer_features(answers)}
