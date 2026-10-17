"""Проверяемость вывода: паспорт доказательств, запас прочности, окно для России, сверка досье.

Всё здесь детерминировано и опирается на ответы decision-модели и найденные документы:
модель не «верит на слово» ни себе, ни LLM.
"""
import math
import re
from urllib.parse import urlparse

from app.pipeline.questions import HARD_EVENT_LEVEL, event_label

# ---------------------------------------------------------------- паспорт доказательств

PASSPORT_RU = {
    "A": "Надёжно: много независимых подтверждений",
    "B": "Достаточно: подтверждения из разных источников",
    "C": "Мало данных: нужно наблюдать",
}


def _domain(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    return host[4:] if host.startswith("www.") else host


def passport(items: list[dict], answers: dict, n_asked: int, min_docs: int = 3) -> dict:
    """Сколько документов decision-модель подтвердила как описывающие именно эту технологию.

    items — фрагменты доказательств в том порядке, в котором они ушли в decision-модель;
    n_asked — сколько из них поместилось в запрос (по ним заданы вопросы doc_N).
    Ссылки из датасета организатора не считаются: это не независимое подтверждение.
    """
    confirmed = []
    for i, it in enumerate(items[:n_asked], 1):
        if it.get("type") == "dataset":
            continue
        a = answers.get(f"doc_{i}") or {}
        if float(a.get("value", 0.0)) >= 0.5:
            confirmed.append(it)
    # Домен издания: у новостей из лент — само издание (поле domain), а не адрес ленты.
    dom = lambda it: it.get("domain") or _domain(it.get("url", "")) or it.get("source", "")  # noqa: E731
    domains = sorted({dom(it) for it in confirmed} - {""})
    science = sum(1 for it in confirmed if it.get("type") in ("science", "preprint"))
    # Независимые источники: разные сайты; научные работы — каждая отдельно (разные исследовательские группы,
    # даже если все лежат на arXiv), но не больше трёх, чтобы один препринт-сервер не давал «A» в одиночку.
    other = {dom(it) for it in confirmed if it.get("type") not in ("science", "preprint")} - {""}
    independent = len(other) + min(science, 3)
    ev_level, ev_ru = event_label((answers.get("event") or {}).get("value"))
    # Подтверждённая новость о раунде или запуске — твёрдое событие, даже если модель оценила событие ниже.
    news_events = [it.get("event") for it in confirmed if it.get("event")]
    if "funding" in news_events and ev_level < 6:
        ev_level, ev_ru = event_label(1.0)
    elif "launch" in news_events and ev_level < 5:
        ev_level, ev_ru = event_label(5 / 6)
    elif "grant" in news_events and ev_level < 3:  # подтверждённый госгрант (NIH, NSF, UKRI)
        ev_level, ev_ru = event_label(3 / 6)
    n = len(confirmed)
    if n >= max(5, min_docs) and independent >= 3 and len(domains) >= 2 and (science >= 1 or ev_level >= HARD_EVENT_LEVEL):
        level = "A"
    elif n >= min_docs and independent >= 2:
        level = "B"
    else:
        level = "C"
    return {
        "level": level,
        "label": PASSPORT_RU[level],
        "checked": min(n_asked, len(items)),
        "confirmed": n,
        "domains": independent,
        "domain_list": domains[:8],
        "science": science,
        "event_level": ev_level,
        "event": ev_ru,
        "hard_event": ev_level >= HARD_EVENT_LEVEL,
        "funding_news": sum(1 for e in news_events if e == "funding"),
        "grants": sum(1 for e in news_events if e == "grant"),
    }


def prob_text(p: float | None) -> str:
    """Вероятность словами без ложной точности: логистическая модель не бывает уверена «на 100%»."""
    if p is None:
        return "не рассчитана"
    if p >= 0.95:
        return "выше 95%"
    if p <= 0.05:
        return "ниже 5%"
    return f"в {p:.0%}"


# ---------------------------------------------------------------- запас прочности

def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-max(min(x, 30), -30)))


def robustness(prob: float | None, contributions: list[dict], intercept: float | None = None) -> dict | None:
    """Что станет с вероятностью, если убрать самый сильный довод «за».

    Модель линейная, поэтому ответ точный: логит минус вклад признака. Логит берём как сумму вкладов
    (если известен свободный член) — восстановление из округлённой вероятности 0.9999 было бы неточным.
    """
    if prob is None or not contributions:
        return None
    if intercept is not None:
        logit = intercept + sum(c["contribution"] for c in contributions)
    else:
        prob = min(max(prob, 1e-6), 1 - 1e-6)
        logit = math.log(prob / (1 - prob))
    pos = [c for c in contributions if c["contribution"] > 0]
    if not pos:
        return {"level": "fragile", "label": "хрупкий", "text": "Нет признаков, которые повышают вероятность.", "p_without": prob}
    top = max(pos, key=lambda c: c["contribution"])
    p_without = _sigmoid(logit - top["contribution"])
    if p_without >= 0.75:
        level, label = "strong", "прочный"
    elif p_without >= 0.5:
        level, label = "stable", "устойчивый"
    else:
        level, label = "fragile", "хрупкий"
    return {
        "level": level,
        "label": label,
        "feature": top["feature"],
        "feature_label": top["label"],
        "p_without": round(p_without, 3),
        "text": f"Если убрать самый сильный довод «{top['label']}», вероятность станет {p_without:.0%}.",
    }


# ---------------------------------------------------------------- окно для России

def mentions(docs, terms: list[str]) -> int:
    """Документы, где действительно встречается термин (поиск Хабра и GDELT возвращает и созвучное)."""
    keys = [t.lower() for t in terms if t and len(t) >= 4]
    if not keys:
        return 0
    n = 0
    for d in docs:
        text = f"{d.title} {d.snippet}".lower()
        if any(k in text for k in keys):
            n += 1
    return n


def russia_window(world_recent: int | None, ru_count: int | None) -> dict:
    """Сравнение мировой активности (научные работы за 2 года) с русскоязычными упоминаниями."""
    if world_recent is None:
        return {"status": "unknown", "label": "Нет данных", "text": "Статистика публикаций OpenAlex недоступна — окно оценить нельзя.", "world": None, "ru": ru_count}
    if ru_count is None:
        return {"status": "unknown", "label": "Нет данных", "text": "Русскоязычные источники недоступны.", "world": world_recent, "ru": None}
    if world_recent < 5:
        status, label, text = "thin", "Мало данных", "В мире пока мало публикаций — окно оценить нельзя."
    elif ru_count == 0:
        status, label, text = "open", "Окно открыто", f"В мире {world_recent} научных работ за 2 года, в русскоязычных источниках упоминаний не найдено."
    elif ru_count <= 4:
        status, label, text = "closing", "Окно закрывается", f"В мире {world_recent} работ за 2 года, в России — первые упоминания ({ru_count})."
    else:
        status, label, text = "closed", "Тема уже обсуждается в России", f"Русскоязычных упоминаний: {ru_count} при {world_recent} работах в мире."
    return {"status": status, "label": label, "text": text, "world": world_recent, "ru": ru_count}


COUNTRY_RU = {"CN": "Китай", "US": "США", "RU": "Россия", "IN": "Индия", "GB": "Великобритания", "DE": "Германия", "JP": "Япония",
              "KR": "Южная Корея", "FR": "Франция", "IT": "Италия", "SG": "Сингапур", "CA": "Канада", "AU": "Австралия"}


def geography(counts: dict[str, int]) -> dict | None:
    """Где ведутся работы за 2 года: топ стран и доли Китая, США и России (от суммы участий стран)."""
    total = sum(counts.values())
    if total < 5:  # по нескольким работам доли ничего не говорят
        return None
    top = sorted(counts.items(), key=lambda x: -x[1])[:5]
    share = lambda c: round(counts.get(c, 0) / total, 3)  # noqa: E731
    return {"top": [{"country": c, "name": COUNTRY_RU.get(c, c), "share": round(n / total, 3)} for c, n in top],
            "china": share("CN"), "usa": share("US"), "russia": share("RU"), "leader": COUNTRY_RU.get(top[0][0], top[0][0])}


def world_recent_works(yearly: dict, year: int) -> int:
    c = {int(k): v for k, v in (yearly or {}).items()}
    return int(c.get(year, 0) + c.get(year - 1, 0))


# ---------------------------------------------------------------- радар технологий банка

# Направления банка: по словам в названии, источниках и досье (без LLM) или по ответу GigaChat в досье.
BANK_AREAS = [
    ("Платежи и переводы", r"\bpayments?\b|\bremittance|\bsettlement\b|\bclearing\b|\bwallets?\b|\bcheckout\b|\bacquiring\b|платеж|платёж|перевод|эквайринг|кошел"),
    ("Цифровые активы и токенизация", r"\btokeni[sz]|\bstablecoins?\b|\bcbdcs?\b|\bblockchain|\bdistributed ledger|\bcrypto(currenc|asset)|\bdefi\b|\bdigital assets?\b|цифров\w* (рубл|валют|актив)|токениз|стейблкоин|блокчейн|криптовалют"),
    ("Кредитование и скоринг", r"\bcredit\b|\blending\b|\bloans?\b|\bcredit scoring|\bunderwrit|\bmortgage|\bbnpl\b|кредит|скоринг|займ|ипотек"),
    ("Антифрод и ПОД/ФТ", r"\bfraud|\bmoney laundering|\baml\b|\banti-money|\bscams?\b|\bmoney mules?\b|\bdeepfakes?\b|\bliveness\b|мошенн|антифрод|отмыван"),
    ("Комплаенс и KYC", r"\bkyc\b|\bcompliance\b|\bregtech\b|\bdigital identity\b|\bidentity verification\b|\bcustomer onboarding\b|комплаенс|идентификаци\w* клиент"),
    ("Кибербезопасность", r"\bcyber|\bsecurity\b|\bsecure\b|\bintrusion|\bmalware|\bpost-quantum|\bzero trust\b|\bvulnerabilit|\bprompt injection|\bphishing|"
                          r"\badversarial|\battacks?\b|\bred[- ]?teaming|\bjailbreak|\bbackdoor|\bpoisoning|\bprivacy attack|кибер|информационн\w* безопасн|уязвим|атак|вредонос|злоумышл"),
    ("ИТ-инфраструктура и данные", r"\bcloud\b|\bdata ?cent(er|re)s?\b|\bgpus?\b|\baccelerators?\b|\binference\b|\bdatabases?\b|\bchiplets?\b|\bserverless\b|\bedge computing\b|облачн|цод|инфраструктур"),
    ("Клиентский сервис и каналы", r"\bcustomer (service|experience|support)\b|\bchatbots?\b|\bvoice assistants?\b|\bconversational\b|\bcontact cent|обслуживани\w* клиент|чат-бот|голосов\w* ассистент"),
    ("Инвестиции и казначейство", r"\btrading\b|\bportfolio\b|\basset management\b|\bwealth\b|\btreasury\b|\bmarket making\b|\brobo-advis|трейдинг|портфел|управлени\w* активами|казначей"),
]
OUTSIDE = "Вне ключевых направлений банка"
HORIZONS = {"pilot": "до 2 лет", "build": "2–5 лет", "research": "5 лет и более"}


def bank_area(text: str, name: str = "") -> str:
    """Направление банка по названию технологии и заголовкам источников.

    Совпадение в названии весит втрое: заголовки статей шумные. Если связи с банком нет (менее двух
    совпадений), честно пишем «вне ключевых направлений», а не приписываем случайную категорию."""
    t, n = text.lower(), name.lower()
    scores = [(len(re.findall(p, t)) + 3 * len(re.findall(p, n)), area) for area, p in BANK_AREAS]
    best = max(scores)
    return best[1] if best[0] >= 2 else OUTSIDE


def bank_radar(name: str, items: list[dict], dossier: dict, passport_: dict | None, status: str) -> dict:
    """Позиция технологии на радаре банка: направление, кольцо (что делать) и горизонт.

    Кольцо: «Пилотировать» — надёжные доказательства (A) и уже есть пилот, релиз или инвестиции;
    «Изучать» — сигнал с достаточными доказательствами; «Наблюдать» — мало подтверждений.
    """
    # Направление определяют прозрачные правила по названию и заголовкам источников. Выбор GigaChat из списка
    # принимается только при совпадении: в прогоне 17.10 он относил микророботов к «Комплаенсу и KYC».
    area = bank_area(" ".join(i.get("title", "") for i in items[:10]), name)
    llm_area = dossier.get("bank_area")
    pp = passport_ or {}
    ev = pp.get("event_level", 0)
    if status == "watch" or pp.get("level") == "C":
        ring = "Наблюдать"
    elif pp.get("level") == "A" and pp.get("hard_event"):
        ring = "Пилотировать"
    else:
        ring = "Изучать"
    horizon = HORIZONS["pilot"] if ev >= 4 else HORIZONS["build"] if ev >= 2 else HORIZONS["research"]
    return {"area": area, "ring": ring, "horizon": horizon, "by": "rules+gigachat" if llm_area == area else "rules",
            "llm_area": llm_area if llm_area and llm_area != area else None}


# ---------------------------------------------------------------- динамика

def dynamics(yearly: dict, today_year: int, years: int = 8) -> list[dict]:
    """Ряд публикаций по годам для графика в карточке (текущий год — неполный, помечается)."""
    c = {int(k): int(v) for k, v in (yearly or {}).items()}
    return [{"year": y, "works": c.get(y, 0), "partial": y == today_year} for y in range(today_year - years + 1, today_year + 1)]


# ---------------------------------------------------------------- сверка досье

CHECK_FIELDS = ("description", "advantage", "case_example", "why_weak_signal")


def split_claims(dossier: dict, limit: int = 10) -> list[tuple[str, str]]:
    """Фактические утверждения досье: (поле, предложение). Гипотезы для банка и риски не проверяются."""
    out = []
    for f in CHECK_FIELDS:
        text = str(dossier.get(f) or "")
        for s in re.split(r"(?<=[.!?])\s+(?=[А-ЯA-Z«\"])", text):
            s = s.strip()
            if len(s) >= 25:
                out.append((f, s))
    return out[:limit]


def quotes(text: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[«\"“]([^»\"”]{12,300})[»\"”]", text or "")]


def quote_found(q: str, evidence_text: str) -> bool:
    norm = lambda s: re.sub(r"\s+", " ", s.lower()).strip()  # noqa: E731
    return norm(q) in norm(evidence_text)


def apply_verification(dossier: dict, claims: list[tuple[str, str]], answers: dict, evidence_text: str, by: str, threshold: float = 0.4) -> dict:
    """Убирает из досье утверждения, которые decision-модель не подтвердила, и цитаты, которых нет в источниках."""
    d = dict(dossier)
    removed = []
    for i, (field, sentence) in enumerate(claims, 1):
        v = float((answers.get(f"claim_{i}") or {}).get("value", 1.0))
        if v < threshold and d.get(field):
            d[field] = d[field].replace(sentence, "").strip()
            removed.append({"field": field, "text": sentence, "score": round(v, 2), "why": "не подтверждено источниками"})
    for field in CHECK_FIELDS:
        for q in quotes(str(d.get(field) or "")):
            if not quote_found(q, evidence_text):
                d[field] = d[field].replace(q, f"{q} [цитата не найдена в источниках]")
                removed.append({"field": field, "text": q, "score": None, "why": "цитата не найдена дословно"})
    d["verification"] = {
        "by": by,
        "checked": len(claims),
        "supported": len(claims) - sum(1 for r in removed if r["score"] is not None),
        "removed": removed,
    }
    return d
