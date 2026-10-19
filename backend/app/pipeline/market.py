"""Рыночный слой сигнала: лестница «от науки до рынка», доводы «против», карта игроков.

Лестница — на фактах, а не на словах модели: каждая ступень заполняется документом, который Jev подтвердила как описывающий
именно эту технологию (из обычных доказательств кандидата или из веб-поиска Brave). У ступени — число документов, первая дата
и пример. Ступени упорядочены от науки к рынку; «дошла до ступени» — самая дальняя заполненная.

Доводы «против» — документы о провале, отказе или, наоборот, о массовости технологии (тогда это уже не ранний сигнал).
Показываются рядом с доводами «за», на место в выдаче не влияют.

Карта игроков — кто публикует работы (организации мира и России, OpenAlex), какие компании и стартапы видны в подтверждениях.
"""
import re

from app.collectors import brave, openalex
from app.collectors.base import RawDoc
from app.collectors.http import HttpClient
from app.pipeline.questions import build_state

STEPS = [
    ("science", "научная работа"), ("patent", "патент"), ("grant", "грант"), ("startup", "стартап"),
    ("funding", "раунд / инвестиции"), ("pilot", "пилот / испытания"), ("contract", "контракт / заказ"),
    ("launch", "серийный продукт / запуск"), ("procurement", "закупка в России"),
]
LABEL = dict(STEPS)


def confirmed_items(items: list[dict], answers: dict, n_asked: int) -> list[dict]:
    """Документы, которые decision-модель подтвердила как описывающие именно эту технологию (как в паспорте)."""
    out = []
    for i, it in enumerate(items[:n_asked], 1):
        if it.get("type") != "dataset" and float((answers.get(f"doc_{i}") or {}).get("value", 0.0)) >= 0.5:
            out.append(it)
    return out


def step_of(it: dict) -> str | None:
    t, ev = it.get("type"), it.get("event")
    if ev == "procurement":
        return "procurement"
    if ev == "patent" or t == "patent":
        return "patent"
    if ev == "grant" or t == "grant":
        return "grant"
    if ev == "startup" or t == "startup":
        return "startup"
    if ev in ("funding", "launch") or it.get("market"):
        return it.get("market") or brave.market_event(f"{it.get('title', '')}. {it.get('snippet', '')}") or ("funding" if ev == "funding" else "launch")
    if t in ("science", "preprint"):
        return "science"
    return None


def ladder(confirmed: list[dict], epo_patents: int = 0) -> dict:
    steps = []
    for key, label in STEPS:
        docs = sorted((it for it in confirmed if step_of(it) == key), key=lambda it: it.get("date") or "9999")
        n = len(docs) + (epo_patents if key == "patent" else 0)
        first = next((d for d in docs if d.get("date")), docs[0] if docs else None)
        steps.append({"key": key, "label": label, "n": n, "first_date": (first or {}).get("date"),
                      "example": (first or {}).get("title", "")[:160] if first else ("патенты EPO" if n else None),
                      "url": (first or {}).get("url")})
    reached = [s for s in steps if s["n"]]
    top = reached[-1] if reached else None
    text = None
    if top:
        since = f" (с {top['first_date'][:4]})" if top.get("first_date") else ""
        text = f"Дошла до ступени «{top['label']}»{since}; заполнено ступеней: {len(reached)} из {len(STEPS)}."
    return {"steps": steps, "reached": top["key"] if top else None, "text": text}


def _item(d: RawDoc) -> dict:
    return {"type": d.source_type, "source": d.source_name, "date": d.published, "title": d.title, "snippet": d.snippet, "url": d.url,
            "event": (d.extra or {}).get("event"), "market": (d.extra or {}).get("market"), "domain": (d.extra or {}).get("publisher_domain")}


async def market_layer(http: HttpClient, dm, name_en: str, name_ru: str, topic: str, items: list[dict], answers: dict, n_asked: int,
                       epo_patents: int = 0, budget: brave.Budget | None = None) -> dict:
    """Лестница и доводы «против» для одного сигнала. Веб-поиск — в пределах бюджета прогона; новые документы подтверждает Jev
    одним вызовом (тот же вопрос «описывает ли документ именно эту технологию?» плюс вопрос о провале или массовости)."""
    found: list[RawDoc] = []
    against: list[RawDoc] = []
    phrase = re.sub(r"\(.*?\)", "", name_en).strip()
    if budget is not None and brave.enabled():
        for coro in (brave.events(http, phrase, budget), brave.patents(http, phrase, budget)):
            try:
                found += await coro
            except Exception:  # noqa: BLE001 — бюджет исчерпан или источник недоступен: лестница строится по тому, что есть
                pass
        if name_ru and re.search(r"[а-яё]", name_ru, re.I):
            try:
                found += await brave.procurement(http, name_ru, budget)
            except Exception:  # noqa: BLE001
                pass
        try:
            against = await brave.against(http, phrase, budget)
        except Exception:  # noqa: BLE001
            against = []
    seen, web = set(), []
    for d in found[:9] + against[:3]:
        if d.url not in seen:
            seen.add(d.url)
            web.append(d)
    confirmed_web, against_ok = [], []
    if web:
        n_ag = {d.url for d in against}
        qs = {f"doc_{i}": {"type": "noul", "instructions": f"Does EVIDENCE item [{i}] actually describe the SUBJECT itself (not just similar words)?"}
              for i in range(1, len(web) + 1)}
        qs.update({f"against_{i}": {"type": "noul", "instructions": f"Does EVIDENCE item [{i}] say that the SUBJECT failed, was discontinued "
                                     "or abandoned, or that it is already a mainstream, widely adopted or standard technology?"}
                   for i, d in enumerate(web, 1) if d.url in n_ag})
        res = await dm.ask(build_state(name_en, topic, [_item(d) for d in web]), qs)
        val = lambda k: float((res.answers.get(k) or {}).get("value", 0.0)) if res.ok else 0.0  # noqa: E731
        for i, d in enumerate(web, 1):
            if val(f"doc_{i}") >= 0.5:
                if d.url in n_ag:
                    if val(f"against_{i}") >= 0.5:
                        against_ok.append(d)
                else:
                    confirmed_web.append(d)
    confirmed = confirmed_items(items, answers, n_asked) + [_item(d) for d in confirmed_web]
    lad = ladder(confirmed, epo_patents)
    return {
        "ladder": lad,
        "against": [{"title": d.title, "url": d.url, "date": d.published, "source": d.source_name,
                     "why": "массовость или стандарт" if re.search(r"widely|standard|mainstream|mature|массов|стандарт", f"{d.title} {d.snippet}", re.I)
                     else "провал или отказ"} for d in against_ok],
        "web_docs": confirmed_web,
        "web_checked": len(web),
    }


async def players(http: HttpClient, phrase: str, year: int, items: list[dict]) -> dict:
    """Карта игроков: организации с работами за 2 года (мир и Россия, OpenAlex) и компании из подтверждений."""
    phrase = re.sub(r"\(.*?\)", "", phrase).strip()
    world, russia = [], []
    try:
        world = await openalex.institution_counts(http, phrase, year - 2)
        russia = await openalex.institution_counts(http, phrase, year - 2, country="RU", n=5)
    except Exception:  # noqa: BLE001 — без карты игроков карточка остаётся полной
        pass
    companies = []
    for it in items:
        t = it.get("title", "")
        if it.get("type") == "startup":  # «Название: однострочник» из каталога YC
            companies.append({"name": t.split(":")[0][:80], "kind": "стартап", "url": it.get("url")})
        elif it.get("event") == "funding" and it.get("type") == "news":
            m = re.match(r"([A-Z][\w\.\-&]+(?:\s+[A-Z][\w\.\-&]+){0,3})\s+(raises|secures|lands|closes|gets|nabs)", t)
            if m:
                companies.append({"name": m.group(1), "kind": "раунд", "url": it.get("url")})
    uniq = {c["name"].lower(): c for c in companies}
    return {"institutions": world, "russia": russia, "companies": list(uniq.values())[:8]}
