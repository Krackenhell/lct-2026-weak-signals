"""П13 (H10, docs/research): «импульс роста» — индикаторы появления темы в литературе, собственный код без LLM.

Классификатор отвечает на вопрос «ранняя технология или зрелая», а не «набирает ли она скорость». Индикаторы ниже —
про скорость. Проверены на машине времени (app/ml/emergence_check.py, data/model/emergence.json); в живом поиске
показывается один индикатор — бейдж «Импульс роста», ранжирование он не меняет.

- young_growth — рост публикаций, приглушённый возрастом темы: молодая и растущая тема выше старой и растущей;
- burst — всплеск последнего года против трёх предыдущих (z-оценка Пуассона);
- escore — прокси EScore (Porter): активность, свежесть и наклон по корням из числа работ;
- yoon_quadrant — квадрант Yoon «рост × видимость» внутри среза: высокий рост при низкой видимости.
"""
import math


def reconstruct_series(f: dict) -> tuple[float, float, float, float, float, float]:
    """Работы по годам s1..s4 (годы c−1..c−4), более ранние и всего — из шести сохранённых признаков машины времени.
    Нужна, потому что строки машины времени хранят признаки, а не ряды; ошибка восстановления — порядка 1e-4."""
    T = math.expm1(f["log_works_total"])
    r2 = math.expm1(f["log_works_recent2"])
    p2 = max(0.0, 2 * math.expm1(math.log1p(r2 / 2) - f["growth2"]))
    s3 = max(0.0, min(p2, f["recent_share3"] * T - r2)) if T else 0.0
    s4 = max(0.0, p2 - s3)
    target = f["accel"] - math.log1p(s3)
    lo, hi = 0.0, r2
    for _ in range(80):  # log1p(r2 − s2) − 2·log1p(s2) убывает по s2 — бисекция
        mid = (lo + hi) / 2
        if math.log1p(r2 - mid) - 2 * math.log1p(mid) > target:
            lo = mid
        else:
            hi = mid
    s2 = (lo + hi) / 2
    s1 = r2 - s2
    older = max(0.0, T - (s1 + s2 + s3 + s4))
    return s1, s2, s3, s4, older, T


def from_series(s1: float, s2: float, s3: float, s4: float, older: float, age_years: float) -> dict:
    sq = math.sqrt
    growth2 = math.log1p((s1 + s2) / 2) - math.log1p((s3 + s4) / 2)
    active = (sq(s1) + sq(s2) + sq(s3)) / 3 - sq(s4 + older / 10)
    recent = sq(s1 + s2) - sq(s3 + s4)
    slope = (sq(s1) - sq(s3)) / 2
    mu = (s2 + s3 + s4) / 3
    return {
        "growth2": growth2,
        "young_growth": growth2 / (1 + (age_years or 0) / 5),
        "burst": (s1 - mu) / sq(mu + 1),
        "escore": 2 * active + recent + slope,
        "works_4y": s1 + s2 + s3 + s4,
    }


def indicators(f: dict) -> dict:
    """Индикаторы по признакам строки машины времени (годы ≥ отсечки не используются: ряд восстановлен из признаков на отсечке)."""
    s1, s2, s3, s4, older, _ = reconstruct_series(f)
    return from_series(s1, s2, s3, s4, older, f.get("age_years", 0))


MIN_WORKS = 5  # меньше 5 работ за 4 года — истории нет, импульс не считаем


def live_impulse(yearly: dict | None, year: int, age_years: float | None) -> dict | None:
    """Бейдж для живого поиска по ряду OpenAlex: полные годы year−1 … year−4 (текущий год неполный)."""
    if not yearly:
        return None
    c = {int(k): int(v) for k, v in yearly.items()}
    s = [c.get(year - k, 0) for k in (1, 2, 3, 4)]
    if sum(s) < MIN_WORKS:
        return {"level": None, "label": "нет научной истории — сигнал по событиям", "works_4y": sum(s)}
    older = sum(v for y, v in c.items() if y < year - 4)
    ind = from_series(*s, older, age_years or 0)
    yg = ind["young_growth"]
    level, label = ("high", "высокий") if yg >= 0.6 else ("medium", "средний") if yg >= 0.2 else ("low", "низкий")
    return {"level": level, "label": label, "young_growth": round(yg, 3), "growth2": round(ind["growth2"], 3), "works_4y": sum(s)}
