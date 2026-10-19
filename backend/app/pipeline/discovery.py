"""Поиск кандидатов по открытому запросу.

1. Собираем «разведочный» корпус свежих документов по подтемам запроса.
2. Извлекаем из него названия конкретных технологий: LLM по текстам документов
   (каждый кандидат привязан к документам-основаниям) + статистический майнинг фраз.
3. Добавляем технологии из базы отслеживаемых сигналов, если они относятся к запросу
   (перепроверяются по живым источникам наравне с новыми, помечаются в выдаче).
"""
import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

import time

from app.collectors import arxiv, crossref, cyberleninka, europepmc, gdelt, grants, habr, hackernews, ml_papers, news_search, openalex, semanticscholar, yc
from app.collectors.base import RawDoc
from app.collectors.http import HttpClient, SourceError
from app.config import get_settings
from app.llm.providers import BaseLLM, LLMResult
from app.llm.tasks import extract_candidates, is_broad
from app.pipeline import routing

STOP = set(
    "a an the of for and or in on to with by from via as at is are be this that these those we our its their using based towards toward "
    "into over under new novel approach approaches method methods study analysis framework system systems model models results paper "
    "survey review case towards large scale efficient effective improved improving learning data use via than more less "
    "has have had been being become becomes became emerged emerging is was were can could will would may might should "
    "rapid growing role impact key current future recent various different traditional potential significant "
    "evolution landscape industry sector literature systematic activities transactions institutions services price".split()
)
GENERIC = {
    "artificial intelligence", "machine learning", "deep learning", "neural network", "neural networks", "large language model",
    "large language models", "language models", "language model", "state of the art", "real world", "real time", "case study",
    "proposed method", "experimental results", "generative ai", "ai systems", "ai models", "computer vision", "natural language",
    "reinforcement learning", "internet of things", "blockchain technology", "financial technology", "high performance",
}
WATCHLIST_DOMAINS = {
    "Финтех": r"финтех|финанс|банк|платеж|платёж|кредит|fintech|payment|bank|finance",
    "Защита ИИ": r"кибер|безопасн|защит|security|cyber|безопасность ии|ai safety",
    "Роботы": r"робот|robot",
    "Edge": r"edge|периферийн|iot|устройств|смартфон|device",
    "Инфраструктура ИИ": r"инфраструктур|дата-центр|цод|чип|полупровод|hardware|infrastructure|datacenter|вычисл",
    "Индустриальный ИИ": r"индустр|промышлен|производств|завод|industrial|manufactur",
}
AI_QUERY = r"\bии\b|искусственн|нейросет|\bai\b|artificial intelligence|машинн"
# Europe PMC подключается для наук о жизни (и, по маршруту источников, для материалов и энергетики): для финтеха
# или роботов он даёт шум. Микрофлюидика, органы на чипе, биосенсоры — тоже науки о жизни (раньше Europe PMC для них не включался).
LIFE_SCIENCE = routing.LIFE_MED
# Обрывки фраз, которые статистика выдаёт за технологии: заголовки Hacker News, биржевые новости,
# фрагменты через «and» («detection and anti-money»), фразы, обрывающиеся на прилагательном («adoption of digital»).
INDUSTRY_COLLECTORS = {"rss", "siliconangle", "yc"}
MAX_LLM_DOCS, INDUSTRY_DOCS = 300, 60
JUNK_FIRST = {"show", "ask", "tell", "hn", "launch"}
JUNK_ANY = {"shares", "stock", "stocks", "ipo", "earnings", "revenue", "billion", "million", "percent", "quarter",
            # заголовки новостей о раундах: «X startup raises $12M Series A» — событие, а не технология
            "raises", "raised", "raise", "series", "funding", "startup", "startups", "round", "nabs", "secures", "valuation",
            # обороты новостных заметок: «today announced», «said today it», «announced that it»
            "today", "announced", "announces", "announce", "said", "says", "unveiled", "unveils", "week", "yesterday"}
JUNK_LAST = {"digital", "financial", "technological", "sized", "driven", "aware", "enabled", "open-source", "related"}


# Хвосты и зачины, которые делают из технологии название раздела или статьи: «solid state battery development»,
# «Dendrimer applications», «Characterization of soft robotic materials». Срезаем — так и поиск по фразе точнее.
TAIL_WORDS = {"development", "developments", "application", "applications", "technology", "technologies", "solution", "solutions",
              "research", "study", "studies", "analysis", "advances", "trends", "investigation", "investigations", "evaluation"}
HEAD = re.compile(r"^(characteri[sz]ation|development|analysis|design|evaluation|study|applications?|advances|towards?|"
                  r"investigation|review|overview|modell?ing|role|use|impact) (of|in|for|on) (the )?", re.I)


def clean_name(name: str) -> str:
    n = HEAD.sub("", re.sub(r"\s+", " ", name.replace("_", " ")).strip())
    words = n.split()
    while len(words) > 1 and words[-1].lower() in TAIL_WORDS:
        words.pop()
    return " ".join(words) or name.strip()


def _junk(low: list[str]) -> bool:
    return low[0] in JUNK_FIRST or low[-1] in JUNK_LAST or any(t in JUNK_ANY for t in low) or "and" in low[1:-1]


def _norm(name: str) -> str:
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    words = [w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w for w in s.split()]
    return " ".join(words)


async def build_corpus(http: HttpClient, plan: dict, on_progress=None) -> list[RawDoc]:
    today = date.today()
    from_date = (today - timedelta(days=int(365 * 2.5))).isoformat()
    subs = plan.get("subqueries", [])[:12]
    tasks = []
    # Округление до суток (как в evidence.gather): иначе граница менялась каждую секунду и запрос к HN никогда не брался из кэша.
    since_ts = (int(time.time()) // 86400) * 86400 - 365 * 86400

    async def hn_docs(q):
        docs, _ = await hackernews.search(http, q, since_ts, 20)
        return docs

    s = get_settings()
    topic = plan.get("topic_en", subs[0] if subs else "")
    europepmc_on = routing.route(plan.get("query", ""), plan)["europepmc_corpus"]
    # Каждый документ помечается поисковой фразой, которая его нашла: по этой метке LLM читает корпус
    # поровну по подтемам (см. llm_candidates), а не первые по порядку запросы.
    groups: list[str] = []

    def add(coro, group: str = "") -> None:
        tasks.append(coro)
        groups.append(group or topic)

    core = plan.get("core_term") or ""
    for e in plan.get("emerging", [])[:6] if core else []:
        # Растущие поднаправления ищем внутри темы: «velocity strings» вместе с «gas lift», а не во всех областях.
        add(openalex.search_within(http, core, e["keyword"], from_date, 20), e["keyword"])
    for i, sq in enumerate(subs):
        add(arxiv.search(http, sq, 20), sq)
        add(openalex.search(http, sq, from_date, 20), sq)
        add(hn_docs(sq), sq)  # ссылки на свежие статьи отраслевых изданий о стартапах и продуктах
        if s.extra_sources and i < 6:
            add(crossref.search(http, sq, from_date, 15), sq)  # все издатели с DOI, в т.ч. неанглоязычные журналы
            if semanticscholar.enabled():
                add(semanticscholar.search(http, sq, today.year - 2, 15), sq)
            if europepmc_on:
                add(europepmc.search(http, sq, from_date, 15), sq)
    add(gdelt.search(http, topic, "6m", 30))
    ru_terms = plan.get("ru_terms", [])[:3]
    for j, ru in enumerate(ru_terms):
        if j == 0:  # GDELT — 1 запрос / 5,5 с: одного русского запроса достаточно, остальное дают Хабр и КиберЛенинка
            add(gdelt.search(http, ru, "12m", 25, lang="russian"), ru)
        add(habr.search(http, ru, 15), ru)
        if s.extra_sources:
            add(cyberleninka.search(http, ru, 15, min_year=today.year - 3), ru)  # русскоязычная наука
    if s.extra_sources and topic:
        add(gdelt.search(http, topic, "12m", 20, lang="chinese"))  # китайские СМИ — крупнейший рынок ранних внедрений
    if s.news_sources and topic:
        # Отраслевые новости и раунды: на них построена большая часть сигналов датасета организатора.
        # Ленты изданий (TechCrunch, The Block, PR Newswire, vc.ru, CNews) — только разрешённые robots.txt.
        topic_text = f"{plan.get('query', '')} {topic}"
        add(news_search.for_topic(http, topic_text, [*subs, topic], "en", 100))
        add(news_search.siliconangle(http, topic, 20))
        for sq in subs[:3]:
            add(news_search.siliconangle(http, sq, 15), sq)
        if ru_terms:
            add(news_search.for_topic(http, topic_text, [plan.get("query", ""), *ru_terms], "ru", 30))
    if s.grant_sources:
        # Проекты, которые фонды уже профинансировали: описывают направления за годы до продуктов.
        for sq in subs[:3]:
            add(grants.nih(http, sq, n=10), sq)
            add(grants.nsf(http, sq, n=10), sq)
            add(grants.ukri(http, sq, n=10), sq)
    if s.ml_sources and re.search(AI_QUERY + r"|robot|робот|edge|вычисл|comput|данн|data|агент|agent", plan.get("query", "") + " " + topic, flags=re.I):
        # Ранние исследования в ИИ: обсуждаемые статьи (HF Papers) и поданные на конференции (OpenReview).
        for sq in subs[:6]:
            add(ml_papers.hf_papers(http, sq, 10, min_year=today.year - 2), sq)
            add(ml_papers.openreview(http, sq, 10, min_year=today.year - 2), sq)
    if s.startup_sources:
        # Стартапы YC последних двух лет по подтемам: описания продуктов, в которые уже вложены деньги.
        for sq in subs[:6]:
            add(yc.search(http, sq, 10, min_year=today.year - 2), sq)
    if s.news_sources and topic:
        if plan.get("zh_terms"):  # китайские техно-СМИ: 36Kr, IT之家, cnBeta, InfoQ China
            add(news_search.for_topic(http, topic_text, plan["zh_terms"], "zh", 30))

    done = 0

    async def wrap(coro):
        nonlocal done
        try:
            return await coro
        except (SourceError, Exception):
            return []
        finally:
            done += 1
            if on_progress:
                await on_progress(done, len(tasks))

    seen, out = set(), []
    for group, batch in zip(groups, await asyncio.gather(*(wrap(t) for t in tasks)), strict=True):
        for d in batch:
            k = d.title.lower()[:90]
            if k and k not in seen:
                seen.add(k)
                d.extra = {**(d.extra or {}), "group": group}
                out.append(d)
    return out


def _round_robin(idx: list[int], key) -> list[int]:
    """Порядок «по кругу»: первый документ каждой группы, затем второй и т. д. (внутри группы порядок сохраняется)."""
    by_group: dict[str, list[int]] = defaultdict(list)
    for i in idx:
        by_group[key(i)].append(i)
    out, k = [], 0
    while len(out) < len(idx):
        out += [g[k] for g in by_group.values() if k < len(g)]
        k += 1
    return out


def mine_phrases(docs: list[RawDoc], limit: int = 40) -> list[dict]:
    """Статистическое извлечение многословных терминов (без LLM): частота по документам."""
    df: Counter = Counter()
    where: dict[str, set[int]] = defaultdict(set)
    surface: dict[str, str] = {}
    for i, d in enumerate(docs):
        if d.language not in ("en", None):
            continue
        text = d.title + ". " + (d.snippet.split(". ")[0] if d.snippet else "")
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text)
        seen_here = set()
        for n in (2, 3, 4):
            for j in range(len(tokens) - n + 1):
                gram = tokens[j : j + n]
                low = [t.lower() for t in gram]
                if low[0] in STOP or low[-1] in STOP or sum(t in STOP for t in low) > 1 or _junk(low):
                    continue
                key = _norm(" ".join(low))
                if key in GENERIC or len(key) < 8:
                    continue
                if key not in seen_here:
                    seen_here.add(key)
                    df[key] += 1
                    where[key].add(i)
                    surface.setdefault(key, " ".join(gram))
    scored = []
    for key, c in df.items():
        if c < 2:
            continue
        n = len(key.split())
        scored.append((c * (1 + 0.3 * (n - 2)), key))
    scored.sort(reverse=True)
    out, taken = [], []
    for _, key in scored:
        if any(key in t or t in key for t in taken):
            continue
        taken.append(key)
        out.append({"name_en": surface[key], "name_ru": "", "doc_idx": sorted(where[key])[:8], "method": "phrase-mining"})
        if len(out) >= limit:
            break
    return out


async def llm_candidates(llm: BaseLLM, topic: str, docs: list[RawDoc], batch: int = 30) -> tuple[list[dict], list[LLMResult]]:
    if llm.provider == "none":
        return [], []
    # Модели отдаётся не более 300 документов: до 240 — свежая наука и прочее (столько же, сколько до подключения
    # новостей), до 60 — отраслевые новости (сначала о раундах и запусках). Без квоты научных документов хватает
    # на все пачки и новости не читаются.
    # Научные документы берутся по кругу по поисковым фразам плана: при простой сортировке по году все места
    # занимали первые подтемы (в корпусе 700–900 документов, свежих — больше, чем мест), а поздние
    # («KV cache», «photonic computing») модель не читала вовсе.
    def year(i):
        return -(int((docs[i].published or "0")[:4] or 0))

    def group(i):
        return docs[i].extra.get("group", "")

    industry = [i for i in range(len(docs)) if docs[i].collector in INDUSTRY_COLLECTORS]
    industry.sort(key=lambda i: (not docs[i].extra.get("event"), year(i)))
    industry = industry[:INDUSTRY_DOCS]
    taken = set(industry)
    rest = [i for i in range(len(docs)) if i not in taken]
    science = sorted((i for i in rest if docs[i].source_type in ("science", "preprint")), key=year)
    other = sorted((i for i in rest if docs[i].source_type not in ("science", "preprint")), key=year)
    rest = (_round_robin(science, group) + _round_robin(other, group))[: MAX_LLM_DOCS - len(industry)]
    chunks = [rest[k : k + batch] for k in range(0, len(rest), batch)] + [industry[k : k + batch] for k in range(0, len(industry), batch)]

    async def one(idx):
        payload = [{"title": docs[i].title, "snippet": docs[i].snippet} for i in idx]
        cands, res = await extract_candidates(llm, topic, payload)
        for c in cands:
            c["doc_idx"] = [idx[j] for j in c["doc_idx"]]
            c["method"] = "llm-extraction"
        return cands, res

    results = await asyncio.gather(*(one(c) for c in chunks))
    return [c for cs, _ in results for c in cs], [r for _, r in results]


def merge(cands: list[dict]) -> list[dict]:
    """Склеивает дубли и синонимы по нормализованному названию и пересечению слов."""
    merged: list[dict] = []
    for c in cands:
        c = {**c, "name_en": clean_name(c["name_en"])}
        key = _norm(c["name_en"])
        if not key or key in GENERIC:
            continue
        words = set(key.split())
        target = None
        for m in merged:
            mw = set(m["_key"].split())
            if key == m["_key"] or (len(words & mw) / max(len(words | mw), 1) >= 0.67):
                target = m
                break
        if target:
            target["doc_idx"] = sorted(set(target["doc_idx"]) | set(c.get("doc_idx", [])))
            target["support"] += 1
            target["methods"].add(c.get("method", ""))
            if c.get("method") == "watchlist":
                # Название организатора побеждает перевод LLM («Purpose-Bound Money» не станет «Цельносвязанными деньгами»).
                target["name_ru"] = c.get("name_ru") or target["name_ru"]
                for k in ("watch_id", "alt_terms", "watch_sources"):
                    target.setdefault(k, c.get(k))
            elif not target["name_ru"] and c.get("name_ru"):
                target["name_ru"] = c["name_ru"]
        else:
            merged.append({"name_ru": "", **c, "_key": key, "support": 1, "methods": {c.get("method", "")}, "doc_idx": list(c.get("doc_idx", []))})
    for m in merged:
        m["methods"] = sorted(x for x in m["methods"] if x)
    return merged


def watchlist(query: str, plan: dict, enabled: bool | None = None) -> list[dict]:
    """Сигналы из базы отслеживания, относящиеся к запросу (по области или по словам запроса)."""
    s = get_settings()
    if not (s.use_watchlist if enabled is None else enabled):
        return []
    seed = Path(s.seed_dir)
    items = json.loads((seed / "weak_signals_2026.json").read_text(encoding="utf-8"))
    terms = json.loads((seed / "positive_terms.json").read_text(encoding="utf-8"))
    q = query.lower()
    domains: set[str] = set()
    if is_broad(query):  # области датасета подмешиваются только к широким запросам («микрофлюидные чипы» ≠ «Инфраструктура ИИ»)
        domains = {d for d, pat in WATCHLIST_DOMAINS.items() if re.search(pat, q)}
        if not domains and re.search(AI_QUERY, q):
            domains = {"Защита ИИ", "Инфраструктура ИИ", "Индустриальный ИИ", "Edge"}
    words = {w for w in re.findall(r"[a-z]{4,}", " ".join(plan.get("subqueries", [])).lower())}
    out = []
    for it in items:
        phrase = terms[str(it["id"])][0]
        overlap = words & set(re.findall(r"[a-z]{4,}", phrase.lower()))
        if it["domain"] in domains or len(overlap) >= 2:
            out.append({
                "name_en": phrase, "name_ru": it["name"], "doc_idx": [], "method": "watchlist", "watch_id": it["id"],
                "alt_terms": terms[str(it["id"])][1:], "watch_sources": it["sources"],
            })
    return out
