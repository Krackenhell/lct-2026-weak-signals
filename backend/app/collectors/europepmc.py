"""Europe PMC: публикации и препринты в науках о жизни (медицина, биотехнологии). Открытый API без ключа."""
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

API = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"


async def search(http: HttpClient, query: str, from_date: str, n: int = 15) -> list[RawDoc]:
    q = query.replace('"', "")
    data = await http.get(
        API,
        params={"query": f'"{q}" AND FIRST_PDATE:[{from_date} TO 3000-01-01]', "format": "json", "pageSize": n, "resultType": "core"},
    )
    docs = []
    for r in (data.get("resultList") or {}).get("result", []):
        title = clean(r.get("title"), 400)
        if not title:
            continue
        is_preprint = r.get("source") == "PPR"
        url = f"https://doi.org/{r['doi']}" if r.get("doi") else f"https://europepmc.org/article/{r.get('source')}/{r.get('id')}"
        journal = ((r.get("journalInfo") or {}).get("journal") or {}).get("title")
        docs.append(
            RawDoc(
                url=url,
                title=title,
                snippet=clean(r.get("abstractText")),
                published=r.get("firstPublicationDate"),
                source_name=journal or ("Europe PMC (препринт)" if is_preprint else "Europe PMC"),
                source_type="preprint" if is_preprint else "science",
                language="en",
                collector="europepmc",
            )
        )
    return docs
