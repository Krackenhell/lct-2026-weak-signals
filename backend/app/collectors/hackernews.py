"""Hacker News (Algolia API): обсуждения в инженерном сообществе — индикатор с пониженным доверием."""
from urllib.parse import urlparse

from app.collectors.base import RawDoc
from app.collectors.http import HttpClient

API = "https://hn.algolia.com/api/v1/search_by_date"


async def search(http: HttpClient, query: str, since_ts: int, n: int = 20) -> tuple[list[RawDoc], int]:
    q = query.replace('"', "")
    data = await http.get(
        API,
        params={"query": f'"{q}"', "tags": "story", "numericFilters": f"created_at_i>{since_ts}", "hitsPerPage": n},
    )
    docs = []
    for h in data.get("hits", []):
        external = h.get("url")
        url = external or f"https://news.ycombinator.com/item?id={h.get('objectID')}"
        docs.append(
            RawDoc(
                url=url,
                title=h.get("title") or "",
                published=(h.get("created_at") or "")[:10] or None,
                # Ссылка на внешнюю статью — это новость/публикация издания (доверие по домену), иначе — обсуждение.
                source_name=(urlparse(external).netloc.removeprefix("www.") + " (через Hacker News)") if external else "Hacker News",
                source_type="news" if external else "community",
                language="en",
                collector="hackernews",
                extra={"points": h.get("points", 0), "discussion": f"https://news.ycombinator.com/item?id={h.get('objectID')}"},
            )
        )
    return [d for d in docs if d.title], int(data.get("nbHits", 0))
