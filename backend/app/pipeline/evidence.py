"""Сбор доказательств по одной технологии: документы из нескольких источников + временные ряды.

Одна и та же функция используется при обучении (для технологий из датасета) и при
обработке запроса (для найденных кандидатов) — поэтому признаки сопоставимы.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.collectors import arxiv, crossref, epo, gdelt, github, grants, hackernews, ml_papers, news_search, openalex, semanticscholar, wikipedia, yc
from app.collectors.base import RawDoc
from app.collectors.http import HttpClient, SourceError
from app.config import get_settings

log = logging.getLogger(__name__)


@dataclass
class Evidence:
    phrase: str
    docs: list[RawDoc] = field(default_factory=list)
    yearly: dict[int, int] = field(default_factory=dict)
    wiki: dict = field(default_factory=dict)
    gh_repos_12m: int | None = None
    hn_12m: int | None = None
    yc_yearly: dict[str, int] = field(default_factory=dict)  # стартапы YC по году набора
    countries: dict[str, int] = field(default_factory=dict)  # работы за 2 года по странам авторов (OpenAlex)
    patents: dict | None = None  # патентные публикации за 3 года и доля Китая (EPO OPS, если есть ключ)
    failed: list[str] = field(default_factory=list)
    today: str = ""


# Секунд на один источник по одному кандидату: зависший источник не держит весь запрос. С запасом на очередь:
# arXiv разрешает 1 запрос в 3 с, и при 12 кандидатах одновременно ожидание доходит до ~40 с.
SOURCE_DEADLINE = 120.0


async def _safe(name: str, coro, default, failed: list[str]):
    try:
        return await asyncio.wait_for(coro, SOURCE_DEADLINE)
    except (SourceError, Exception) as exc:  # источник недоступен — продолжаем без него
        log.info("evidence source %s failed: %s", name, exc)
        failed.append(name)
        return default


def search_phrase(name: str) -> str:
    """Поисковая фраза из названия: без скобок, кавычек и лишних слов (точный поиск по фразе)."""
    s = re.sub(r"\(.*?\)|\[.*?\]|[\"«»“”]", " ", name)
    s = re.split(r"[:;/]| - | — ", s)[0].replace("_", " ")
    if " " not in s.strip() and s.count("-") >= 2:  # «slug»-названия вида behavior-aware-fraud-detection
        s = s.replace("-", " ")
    words = s.split()
    return " ".join(words[:6]).strip() or name


async def gather(http: HttpClient, phrase: str, today: date | None = None, with_news: bool = True, with_repos: bool = True, with_extra: bool | None = None,
                 with_gh_count: bool = True, with_news_search: bool | None = None) -> Evidence:
    phrase = search_phrase(phrase)
    today = today or date.today()
    year_ago = today - timedelta(days=365)
    since_ts = int(datetime.combine(year_ago, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    ev = Evidence(phrase=phrase, today=today.isoformat())
    f = ev.failed

    tasks = {
        "arxiv": _safe("arxiv", arxiv.search(http, phrase, 15), [], f),
        "openalex_years": _safe("openalex", openalex.yearly_counts(http, phrase), {}, f),
        "wiki": _safe("wikipedia", wikipedia.lookup(http, phrase), {}, f),
        "hn": _safe("hackernews", hackernews.search(http, phrase, since_ts, 10), ([], None), f),
    }
    if with_gh_count and with_repos:
        # Один поисковый запрос вместо двух: GitHub — самый медленный источник по лимиту (30 запросов в минуту).
        tasks["github_both"] = _safe("github", github.created_with_top(http, phrase, year_ago.isoformat(), today.isoformat(), 3), (None, []), f)
    elif with_gh_count:
        tasks["github"] = _safe("github", github.count_created(http, phrase, year_ago.isoformat(), today.isoformat()), None, f)
    elif with_repos:
        tasks["github_top"] = _safe("github", github.top_repos(http, phrase, 3), [], f)
    if with_news:
        tasks["news"] = _safe("gdelt", gdelt.search(http, phrase, "12m", 12), [], f)
    if with_extra if with_extra is not None else get_settings().extra_sources:
        # Вторая научная база: независимое подтверждение для паспорта доказательств.
        # В числовые признаки не входит (они считаются только по CORE_COLLECTORS), поэтому модель не смещается.
        since = (today - timedelta(days=3 * 365)).isoformat()
        tasks["crossref"] = _safe("crossref", crossref.search(http, phrase, since, 8), [], f)
        if with_news_search is not False:
            # Работы OpenAlex за 3 года: в нефтегазе, химии, материалах, медицине arXiv почти пуст, и без этих
            # документов decision-модели нечего подтверждать (кандидат уходил в «Наблюдать» из-за пустого паспорта).
            tasks["openalex_docs"] = _safe("openalex", openalex.search(http, phrase, since, 8), [], f)
        if semanticscholar.enabled():
            tasks["s2"] = _safe("semanticscholar", semanticscholar.search(http, phrase, today.year - 3, 8), [], f)
    if with_news_search if with_news_search is not None else get_settings().news_sources:
        # Отраслевые новости о технологии: раунды, запуски, пилоты (в числовые признаки не входят).
        # Ленты изданий кэшируются один раз за запуск, отбор по названию технологии — без новых запросов.
        # Поиск SiliconANGLE по каждому кандидату убран: сайт отвечает медленно, и 30 запросов с паузами занимали до 100 с
        # (замер 19.10); его новости и так попадают в корпус при сборе по подтемам и ленте издания.
        tasks["gnews"] = _safe("rss", news_search.matching(http, [phrase], "en", 10, min_score=3), [], f)
    if with_news_search is not False and (with_extra if with_extra is not None else get_settings().extra_sources):
        # География работ за 2 года: доля Китая, США, России (один запрос group_by в OpenAlex).
        tasks["countries"] = _safe("openalex_countries", openalex.country_counts(http, phrase, today.year - 2), {}, f)
    if epo.enabled() and with_news_search is not False:
        # Патенты за 3 года и доля Китая (EPO OPS, только при наличии ключа).
        tasks["patents"] = _safe("epo", epo.patent_counts(http, phrase), None, f)
        tasks["patent_docs"] = _safe("epo", epo.search(http, phrase, 3), [], f)
    if get_settings().startup_sources and with_news_search is not False:
        # Стартапы YC, которые строят технологию: ранний рыночный сигнал (в числовые признаки не входит).
        tasks["yc"] = _safe("yc", yc.search(http, phrase, 3), [], f)
        tasks["yc_yearly"] = _safe("yc", yc.yearly(http, phrase), {}, f)
    if get_settings().ml_sources and with_news_search is not False:
        # Обсуждаемые ML-статьи и поданные на конференции: независимые от arXiv-поиска подтверждения.
        tasks["hf"] = _safe("hfpapers", ml_papers.hf_papers(http, phrase, 3, min_year=today.year - 3), [], f)
        tasks["or"] = _safe("openreview", ml_papers.openreview(http, phrase, 3, min_year=today.year - 3), [], f)
    if get_settings().grant_sources and with_news_search is not False:
        # Госгранты за 3 года: NIH, NSF, UKRI (в числовые признаки не входят, событие «грант» — в паспорт).
        tasks["nih"] = _safe("nih", grants.nih(http, phrase, n=4), [], f)
        tasks["nsf"] = _safe("nsf", grants.nsf(http, phrase, n=4), [], f)
        tasks["ukri"] = _safe("ukri", grants.ukri(http, phrase, n=4), [], f)

    results = dict(zip(tasks, await asyncio.gather(*tasks.values()), strict=False))
    ev.yearly = results["openalex_years"]
    ev.wiki = results["wiki"]
    ev.yc_yearly = results.get("yc_yearly") or {}
    ev.countries = results.get("countries") or {}
    ev.patents = results.get("patents")
    ev.gh_repos_12m = results.get("github")
    if "github_both" in results:
        ev.gh_repos_12m, results["github_top"] = results["github_both"]
    hn_docs, ev.hn_12m = results["hn"]
    ev.docs = [*results["arxiv"], *results.get("openalex_docs", []), *results.get("crossref", []), *results.get("s2", []),
               *results.get("news", []), *results.get("gnews", []), *results.get("sa", []),
               *results.get("nih", []), *results.get("nsf", []), *results.get("ukri", []), *results.get("yc", []),
               *results.get("hf", []), *results.get("or", []), *results.get("patent_docs", []), *results.get("github_top", []), *hn_docs]
    ev.docs = _dedupe(ev.docs)
    return ev


def _dedupe(docs: list[RawDoc]) -> list[RawDoc]:
    seen, out = set(), []
    for d in docs:
        key = re.sub(r"v\d+$", "", d.url.lower().rstrip("/"))  # версии препринта arXiv — один документ
        tkey = d.title.lower()[:80]
        if key in seen or tkey in seen:
            continue
        seen.update({key, tkey})
        out.append(d)
    return out


def evidence_items(ev: Evidence, limit: int = 12) -> list[dict]:
    """Фрагменты для decision-модели: сначала научные, затем по свежести."""
    order = {"science": 0, "preprint": 1, "news": 2, "repository": 3, "community": 4}
    docs = sorted(ev.docs, key=lambda d: (order.get(d.source_type, 5), -(int((d.published or "0000")[:4]))))
    # Новости о раундах и запусках не должны вытесняться научными текстами: до трёх таких новостей идут
    # в доказательства обязательно (decision-модель видит событие, паспорт — независимое издание).
    # Гранту — одно место из трёх, чтобы госфинансирование не вытесняло рынок (раунды, запуски).
    market = [d for d in docs if (d.extra or {}).get("event") in ("funding", "launch")]
    granted = [d for d in docs if (d.extra or {}).get("event") == "grant"]
    events = market[:2] + granted[:1]
    events += [d for d in market[2:] + granted[1:] if d not in events][: 3 - len(events)]
    rest = [d for d in docs if d not in events]
    docs = rest[: max(limit - len(events), 0)] + events
    return [
        {"type": d.source_type, "source": d.source_name, "date": d.published, "title": d.title, "snippet": d.snippet, "url": d.url,
         "domain": (d.extra or {}).get("publisher_domain"), "event": (d.extra or {}).get("event")}
        for d in docs[:limit]
    ]
