"""КиберЛенинка: русскоязычные научные статьи (открытый доступ). Нужна для поиска по-русски и для «окна для России»."""
import re

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

API = "https://cyberleninka.ru/api/search"
BASE = "https://cyberleninka.ru"


def _strip(s: str | None) -> str:
    return re.sub(r"<[^>]+>", "", s or "")


async def search(http: HttpClient, query: str, n: int = 15, min_year: int | None = None) -> list[RawDoc]:
    data = await http.post(API, {"mode": "articles", "q": query.replace('"', ""), "size": n, "from": 0})
    docs = []
    for a in data.get("articles", []) or []:
        year = a.get("year")
        if min_year and isinstance(year, int) and year < min_year:
            continue
        title = clean(_strip(a.get("name")), 400)
        if not title or not a.get("link"):
            continue
        docs.append(
            RawDoc(
                url=BASE + a["link"],
                title=title,
                snippet=clean(_strip(a.get("annotation"))),
                published=f"{year}-01-01" if isinstance(year, int) else None,
                source_name=f"КиберЛенинка: {a.get('journal') or 'журнал'}",
                source_type="science",
                language="ru",
                collector="cyberleninka",
                extra={"authors": (a.get("authors") or [])[:6]},
            )
        )
    return docs
