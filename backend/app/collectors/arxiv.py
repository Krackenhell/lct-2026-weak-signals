"""arXiv: препринты, самый ранний научный сигнал. Официальный API, 1 запрос / 3 с."""
import feedparser

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

API = "https://export.arxiv.org/api/query"


def _phrase(q: str) -> str:
    q = q.replace('"', "").strip()
    return f'all:"{q}"' if " " in q else f"all:{q}"


async def search(http: HttpClient, query: str, max_results: int = 50) -> list[RawDoc]:
    text = await http.get(
        API,
        params={
            "search_query": _phrase(query),
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
        as_json=False,
    )
    feed = feedparser.parse(text)
    docs = []
    for e in feed.entries:
        docs.append(
            RawDoc(
                url=e.get("id", "").replace("http://", "https://"),
                title=clean(e.get("title"), 400),
                snippet=clean(e.get("summary")),
                published=(e.get("published") or "")[:10] or None,
                source_name="arXiv",
                source_type="preprint",
                language="en",
                collector="arxiv",
                extra={"authors": [a.get("name") for a in e.get("authors", [])][:6]},
            )
        )
    return docs


