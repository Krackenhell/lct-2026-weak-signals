"""Сбор доказательств по одной технологии: документы из нескольких источников + временные ряды.

Одна и та же функция используется при обучении (для технологий из датасета) и при
обработке запроса (для найденных кандидатов) — поэтому признаки сопоставимы.
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from app.collectors import arxiv, gdelt, github, hackernews, openalex, wikipedia
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
    failed: list[str] = field(default_factory=list)
    today: str = ""


async def _safe(name: str, coro, default, failed: list[str]):
    try:
        return await coro
    except (SourceError, Exception) as exc:  # источник недоступен — продолжаем без него
        log.info("evidence source %s failed: %s", name, exc)
        failed.append(name)
        return default


async def gather(http: HttpClient, phrase: str, today: date | None = None, with_news: bool = True, with_repos: bool = True) -> Evidence:
    s = get_settings()
    today = today or date.today()
    year_ago = today - timedelta(days=365)
    since_ts = int(datetime.combine(year_ago, datetime.min.time(), tzinfo=timezone.utc).timestamp())
    ev = Evidence(phrase=phrase, today=today.isoformat())
    f = ev.failed

    tasks = {
        "arxiv": _safe("arxiv", arxiv.search(http, phrase, 15), [], f),
        "openalex_years": _safe("openalex", openalex.yearly_counts(http, phrase), {}, f),
        "wiki": _safe("wikipedia", wikipedia.lookup(http, phrase), {}, f),
        "github": _safe("github", github.count_created(http, phrase, year_ago.isoformat(), today.isoformat()), None, f),
        "hn": _safe("hackernews", hackernews.search(http, phrase, since_ts, 10), ([], None), f),
    }
    if s.openalex_api_key:
        tasks["openalex_docs"] = _safe("openalex", openalex.search(http, phrase, (today - timedelta(days=3 * 365)).isoformat(), 12), [], f)
    if with_repos:
        tasks["github_top"] = _safe("github", github.top_repos(http, phrase, 3), [], f)
    if with_news:
        tasks["news"] = _safe("gdelt", gdelt.search(http, phrase, "12m", 12), [], f)

    results = dict(zip(tasks, await asyncio.gather(*tasks.values())))
    ev.yearly = results["openalex_years"]
    ev.wiki = results["wiki"]
    ev.gh_repos_12m = results["github"]
    hn_docs, ev.hn_12m = results["hn"]
    ev.docs = [*results["arxiv"], *results.get("openalex_docs", []), *results.get("news", []), *results.get("github_top", []), *hn_docs]
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
    return [
        {"type": d.source_type, "source": d.source_name, "date": d.published, "title": d.title, "snippet": d.snippet}
        for d in docs[:limit]
    ]
