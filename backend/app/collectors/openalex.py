"""OpenAlex: научные публикации и их годовая динамика. Официальный открытый API."""
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient
from app.config import get_settings

API = "https://api.openalex.org/works"


def _auth() -> dict:
    s = get_settings()
    p = {}
    from app.collectors.http import openalex_key

    if openalex_key():
        p["api_key"] = openalex_key()
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
    return _docs(data)


def _docs(data: dict) -> list[RawDoc]:
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


async def keyword_groups(http: HttpClient, phrase: str, years: str) -> dict[str, tuple[str, int]]:
    """Ключевые слова OpenAlex в работах с фразой за годы years («2025-2026»): id → (название, число работ)."""
    data = await http.get(API, params={"filter": f"{_phrase_filter(phrase)},publication_year:{years}", "group_by": "keywords.id", **_auth()})
    return {str(g.get("key")): (str(g.get("key_display_name") or ""), int(g.get("count") or 0)) for g in data.get("group_by", []) if g.get("key")}


async def count(http: HttpClient, flt: str) -> int:
    """Число работ по фильтру OpenAlex (без самих работ)."""
    data = await http.get(API, params={"filter": flt, "per-page": 1, "select": "id", **_auth()})
    return int((data.get("meta") or {}).get("count") or 0)


async def search_within(http: HttpClient, core: str, query: str, from_date: str, per_page: int = 20) -> list[RawDoc]:
    """Работы, где есть и тема (core), и поднаправление (query): «rhombohedral» внутри «multilayer graphene»."""
    data = await http.get(
        API,
        params={"filter": f"{_phrase_filter(core)},from_publication_date:{from_date}", "search": query.replace('"', ""),
                "per_page": per_page, "select": "id,doi,title,publication_date,abstract_inverted_index,primary_location,type,language", **_auth()},
    )
    return _docs(data)


async def country_counts(http: HttpClient, phrase: str, from_year: int, to_year: int | None = None) -> dict[str, int]:
    """Число работ по странам организаций авторов (ISO-код), один запрос. Работа с авторами из
    нескольких стран учитывается в каждой — поэтому доли считаются от суммы, а не от числа работ."""
    years = f"{from_year}-{to_year}" if to_year else f"{from_year}-"
    data = await http.get(
        API, params={"filter": f"{_phrase_filter(phrase)},publication_year:{years}", "group_by": "authorships.institutions.country_code", **_auth()}
    )
    out = {}
    for g in data.get("group_by", []):
        key = str(g.get("key") or "").rsplit("/", 1)[-1].upper()
        if len(key) == 2:
            out[key] = int(g.get("count") or 0)
    return out


async def institution_counts(http: HttpClient, phrase: str, from_year: int, country: str | None = None, n: int = 8) -> list[dict]:
    """Организации, чьи авторы публикуют работы с фразой с from_year (один запрос group_by): карта игроков.
    country — ISO-код (например, RU): только организации этой страны."""
    flt = f"{_phrase_filter(phrase)},publication_year:{from_year}-"
    if country:
        # group_by по работам страны считал бы и иностранных соавторов: берём сами работы и только организации этой страны.
        flt += f",authorships.institutions.country_code:{country.lower()}"
        data = await http.get(API, params={"filter": flt, "select": "authorships", "per_page": 100, **_auth()})
        counts: dict[str, int] = {}
        for w in data.get("results", []):
            seen = set()
            for a in w.get("authorships") or []:
                for inst in a.get("institutions") or []:
                    name = inst.get("display_name") or ""
                    if (inst.get("country_code") or "").upper() == country.upper() and name and name not in seen:
                        seen.add(name)
                        counts[name] = counts.get(name, 0) + 1
        return [{"name": k, "works": v} for k, v in sorted(counts.items(), key=lambda kv: -kv[1])][:n]
    data = await http.get(API, params={"filter": flt, "group_by": "authorships.institutions.id", **_auth()})
    out = []
    for g in data.get("group_by", []):
        name = g.get("key_display_name") or ""
        if name and name.lower() not in ("unknown", "null"):
            out.append({"name": name, "works": int(g.get("count") or 0)})
    return out[:n]


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
