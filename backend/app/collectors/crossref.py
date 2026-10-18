"""Crossref: метаданные научных публикаций всех издателей с DOI (в том числе неанглоязычных). Открытый API без ключа."""
import re

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

API = "https://api.crossref.org/works"
SKIP_TYPES = {"peer-review", "component", "dataset", "journal-issue", "proceedings", "book-series"}


def _date(item: dict) -> str | None:
    parts = ((item.get("published") or {}).get("date-parts") or [[None]])[0]
    if not parts or not parts[0]:
        return None
    y, m, d = (list(parts) + [1, 1])[:3]
    return f"{int(y):04d}-{int(m or 1):02d}-{int(d or 1):02d}"


async def search(http: HttpClient, query: str, from_date: str, rows: int = 20) -> list[RawDoc]:
    data = await http.get(
        API,
        params={
            "query.bibliographic": query.replace('"', ""),
            "rows": rows,
            "filter": f"from-pub-date:{from_date}",
            "select": "DOI,title,published,abstract,container-title,type",
        },
    )
    docs = []
    for it in (data.get("message") or {}).get("items", []):
        title = clean(" ".join(it.get("title") or []), 400)
        if not title or it.get("type") in SKIP_TYPES:
            continue
        abstract = re.sub(r"<[^>]+>", " ", it.get("abstract") or "")  # аннотации приходят в разметке JATS
        docs.append(
            RawDoc(
                url=f"https://doi.org/{it['DOI']}" if it.get("DOI") else "",
                title=title,
                snippet=clean(abstract),
                published=_date(it),
                source_name=clean(" ".join(it.get("container-title") or []), 200) or "Crossref",
                source_type="preprint" if it.get("type") == "posted-content" else "science",
                language="ru" if re.search(r"[а-яё]", title.lower()) else "en",
                collector="crossref",
            )
        )
    return [d for d in docs if d.url]
