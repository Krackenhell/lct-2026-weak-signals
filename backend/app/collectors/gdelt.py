"""GDELT DOC 2.0: мировые новости на 65 языках (включая русский), открытый API без ключа."""
from datetime import datetime

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

API = "https://api.gdeltproject.org/api/v2/doc/doc"

LANG = {"russian": "ru", "english": "en", "chinese": "zh", "german": "de", "french": "fr", "japanese": "ja"}


def _q(query: str, lang: str | None) -> str:
    query = query.replace('"', "").strip()
    q = f'"{query}"' if " " in query else query
    if lang:
        q += f" sourcelang:{lang}"
    return q


def _date(seendate: str | None) -> str | None:
    try:
        return datetime.strptime(seendate[:8], "%Y%m%d").date().isoformat()
    except (TypeError, ValueError):
        return None


async def search(http: HttpClient, query: str, timespan: str = "12m", max_records: int = 40, lang: str | None = None) -> list[RawDoc]:
    data = await http.get(
        API,
        params={"query": _q(query, lang), "mode": "artlist", "maxrecords": max_records, "timespan": timespan, "format": "json", "sort": "hybridrel"},
    )
    docs = []
    for a in data.get("articles", []) or []:
        docs.append(
            RawDoc(
                url=a.get("url", ""),
                title=clean(a.get("title"), 400),
                published=_date(a.get("seendate")),
                source_name=a.get("domain", ""),
                source_type="news",
                language=LANG.get((a.get("language") or "").lower(), "en"),
                collector="gdelt",
            )
        )
    return [d for d in docs if d.url and d.title]


async def volume(http: HttpClient, query: str, timespan: str = "24m") -> list[tuple[str, float]]:
    """Доля новостей с фразой по месяцам (нормированная интенсивность освещения)."""
    data = await http.get(API, params={"query": _q(query, None), "mode": "timelinevol", "timespan": timespan, "format": "json"})
    series = (data.get("timeline") or [{}])[0].get("data", [])
    return [(p.get("date", "")[:8], float(p.get("value", 0))) for p in series]
