"""OpenAlex: научные публикации и их годовая динамика. Официальный открытый API."""
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient
from app.config import get_settings

API = "https://api.openalex.org/works"


def _auth() -> dict:
    s = get_settings()
    p = {}
    if s.openalex_api_key:
        p["api_key"] = s.openalex_api_key
    if s.openalex_email:
        p["mailto"] = s.openalex_email
    return p


def _abstract(inv: dict | None) -> str:
    if not inv:
        return ""
    pos = {}
    for word, idx in inv.items():
        for i in idx:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos))


def _phrase_filter(q: str) -> str:
    q = q.replace('"', "").replace(",", " ").strip()
    return f'title_and_abstract.search:"{q}"' if " " in q else f"title_and_abstract.search:{q}"


async def search(http: HttpClient, query: str, from_date: str, per_page: int = 50) -> list[RawDoc]:
    data = await http.get(
        API,
        params={
            "filter": f"{_phrase_filter(query)},from_publication_date:{from_date}",
            "sort": "relevance_score:desc",
            "per_page": per_page,
            "select": "id,doi,title,publication_date,abstract_inverted_index,primary_location,type,language",
            **_auth(),
        },
    )
    docs = []
    for w in data.get("results", []):
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {}).get("display_name") or "OpenAlex"
        wtype = w.get("type") or "article"
        url = w.get("doi") or loc.get("landing_page_url") or w.get("id")
        docs.append(
            RawDoc(
                url=url,
                title=clean(w.get("title"), 400),
                snippet=clean(_abstract(w.get("abstract_inverted_index"))),
                published=w.get("publication_date"),
                source_name=src,
                source_type="preprint" if wtype == "preprint" else "science",
                language=w.get("language") or "en",
                collector="openalex",
                extra={"openalex_id": w.get("id"), "type": wtype},
            )
        )
    return [d for d in docs if d.title]


async def yearly_counts(http: HttpClient, phrase: str) -> dict[int, int]:
    """Число работ с фразой в названии/аннотации по годам публикации."""
    data = await http.get(
        API, params={"filter": _phrase_filter(phrase), "group_by": "publication_year", **_auth()}
    )
    out = {}
    for g in data.get("group_by", []):
        try:
            out[int(g["key"])] = int(g["count"])
        except (KeyError, ValueError, TypeError):
            continue
    return out
