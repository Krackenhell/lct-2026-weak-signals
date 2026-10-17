"""Semantic Scholar: научные работы с самым широким покрытием по компьютерным наукам.

Без ключа API почти сразу отвечает 429, поэтому источник включается только при заданном S2_API_KEY
(бесплатно по заявке на semanticscholar.org/product/api)."""
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient
from app.config import get_settings

API = "https://api.semanticscholar.org/graph/v1/paper/search"


def enabled() -> bool:
    return bool(get_settings().s2_api_key)


async def search(http: HttpClient, query: str, from_year: int, n: int = 20) -> list[RawDoc]:
    if not enabled():
        return []
    data = await http.get(
        API,
        params={"query": query.replace('"', ""), "limit": n, "year": f"{from_year}-", "fields": "title,abstract,year,publicationDate,venue,externalIds,url,publicationTypes"},
        headers={"x-api-key": get_settings().s2_api_key},
    )
    docs = []
    for p in data.get("data", []) or []:
        title = clean(p.get("title"), 400)
        if not title:
            continue
        ids = p.get("externalIds") or {}
        url = f"https://doi.org/{ids['DOI']}" if ids.get("DOI") else (f"https://arxiv.org/abs/{ids['ArXiv']}" if ids.get("ArXiv") else p.get("url") or "")
        docs.append(
            RawDoc(
                url=url,
                title=title,
                snippet=clean(p.get("abstract")),
                published=p.get("publicationDate") or (f"{p['year']}-01-01" if p.get("year") else None),
                source_name=p.get("venue") or "Semantic Scholar",
                source_type="preprint" if ids.get("ArXiv") and not ids.get("DOI") else "science",
                language="en",
                collector="semanticscholar",
            )
        )
    return [d for d in docs if d.url]
