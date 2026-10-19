"""Ещё четыре научных и инженерных источника (официальные API, подключены 20.10):

- PubMed (NCBI E-utilities, ключ NCBI_API_KEY — 10 запросов/с): рецензируемая биомедицина;
- NASA ADS (токен NASA_ADS_TOKEN, 5000 запросов/сутки): физика, материалы, астрофизика, приборы;
- bioRxiv и medRxiv (без ключа): препринты наук о жизни. У API нет поиска по словам — только выгрузка по датам, поэтому
  свежий каталог (последние BIORXIV_DAYS дней) загружается в фоне раз в сутки, а поиск идёт по нему локально;
- Stack Exchange (ключ STACKEXCHANGE_KEY, 10 000 запросов/сутки): вопросы инженеров — признак, что технология пошла в практику.

В числовые признаки классификатора не входят: только документы-доказательства, паспорт и лестница.
"""
import asyncio
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient, SourceError
from app.config import get_settings

log = logging.getLogger(__name__)


def _words(phrase: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{3,}", phrase.lower()) if w not in {"and", "for", "the", "with", "based"}]


# ---------------------------------------------------------------- PubMed

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


_MON = {m: i for i, m in enumerate(("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


def _pubmed_date(it: dict) -> str | None:
    """Дата электронной публикации; дата номера журнала бывает в будущем (выпуск 2027 года вышел онлайн в 2026-м)."""
    for raw in (it.get("epubdate"), it.get("sortpubdate"), it.get("pubdate")):
        m = re.match(r"(\d{4})(?:[/\s-]+(\w{1,3}))?(?:[/\s-]+(\d{1,2}))?", raw or "")
        if not m:
            continue
        mon = m.group(2) or "1"
        month = int(mon) if mon.isdigit() else _MON.get(mon[:3].lower(), 1)
        d = f"{m.group(1)}-{month:02d}-{int(m.group(3) or 1):02d}"
        return min(d, date.today().isoformat())
    return None


async def pubmed(http: HttpClient, phrase: str, n: int = 8, years: int = 3) -> tuple[list[RawDoc], int]:
    """Работы PubMed с фразой в названии или аннотации за years лет: (документы, всего найдено)."""
    s = get_settings()
    if not s.ncbi_api_key:
        return [], 0
    y = date.today().year
    term = f'"{phrase.replace(chr(34), "")}"[tiab] AND {y - years}:{y}[dp]'
    key = {"api_key": s.ncbi_api_key}
    ids = await http.get(f"{EUTILS}/esearch.fcgi", params={"db": "pubmed", "term": term, "retmode": "json", "retmax": n, "sort": "pub_date", **key})
    res = ids.get("esearchresult") or {}
    idlist, total = res.get("idlist") or [], int(res.get("count") or 0)
    if not idlist:
        return [], total
    summ = await http.get(f"{EUTILS}/esummary.fcgi", params={"db": "pubmed", "id": ",".join(idlist), "retmode": "json", **key})
    docs = []
    for pmid in idlist:
        it = (summ.get("result") or {}).get(pmid) or {}
        title = clean(it.get("title"), 400)
        if not title:
            continue
        pub = _pubmed_date(it)
        docs.append(RawDoc(url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", title=title, snippet=clean(f"{it.get('fulljournalname') or it.get('source') or ''}", 300),
                           published=pub, source_name=f"PubMed ({it.get('source') or 'журнал'})", source_type="science", language="en", collector="pubmed"))
    return docs, total


# ---------------------------------------------------------------- NASA ADS

ADS = "https://api.adsabs.harvard.edu/v1/search/query"


async def ads(http: HttpClient, phrase: str, n: int = 8, years: int = 3) -> tuple[list[RawDoc], int]:
    """Работы NASA ADS с фразой в аннотации за years лет (рецензируемые и препринты): (документы, всего найдено)."""
    s = get_settings()
    if not s.nasa_ads_token:
        return [], 0
    y = date.today().year
    data = await http.get(ADS, params={"q": f'abs:"{phrase.replace(chr(34), "")}" year:{y - years}-{y}', "fl": "title,bibcode,pubdate,doi,pub,abstract,doctype",
                                       "rows": n, "sort": "date desc"},
                          headers={"Authorization": f"Bearer {s.nasa_ads_token}"})
    resp = data.get("response") or {}
    docs = []
    for d in resp.get("docs") or []:
        title = clean(" ".join(d.get("title") or []), 400)
        if not title:
            continue
        doi = (d.get("doi") or [None])[0]
        pub = (d.get("pubdate") or "")[:7]
        docs.append(RawDoc(url=f"https://doi.org/{doi}" if doi else f"https://ui.adsabs.harvard.edu/abs/{d.get('bibcode')}/abstract",
                           title=title, snippet=clean(d.get("abstract"), 600), published=f"{pub}-01" if re.match(r"\d{4}-\d{2}$", pub) and not pub.endswith("-00") else (f"{pub[:4]}-01-01" if pub else None),
                           source_name=f"NASA ADS ({d.get('pub') or 'журнал'})", source_type="preprint" if d.get("doctype") == "eprint" else "science",
                           language="en", collector="ads"))
    return docs, int(resp.get("numFound") or 0)


# ---------------------------------------------------------------- bioRxiv / medRxiv

BIORXIV = "https://api.biorxiv.org/details/{server}/{start}/{end}/{cursor}"
_CATALOG: dict = {"loaded_at": 0.0, "items": [], "loading": False}


async def _load_catalog(http: HttpClient, days: int) -> None:
    end = date.today()
    start = end - timedelta(days=days)
    items = []
    for server in ("biorxiv", "medrxiv"):
        cursor = 0
        while True:
            try:
                data = await http.get(BIORXIV.format(server=server, start=start.isoformat(), end=end.isoformat(), cursor=cursor))
            except SourceError as exc:
                log.info("biorxiv catalog %s stopped at %s: %s", server, cursor, exc)
                break
            batch = data.get("collection") or []
            items += [{**it, "server": server} for it in batch]
            total = int(((data.get("messages") or [{}])[0]).get("total") or 0)
            cursor += len(batch)
            if not batch or cursor >= total:
                break
    if items:
        _CATALOG.update(items=items, loaded_at=time.time())
        log.info("biorxiv catalog: %s preprints for %s days", len(items), days)


def catalog_ready() -> bool:
    return bool(_CATALOG["items"]) and time.time() - _CATALOG["loaded_at"] < 36 * 3600


def ensure_catalog() -> None:
    """Запускает фоновую загрузку свежего каталога bioRxiv/medRxiv (раз в сутки); прогон не ждёт её."""
    s = get_settings()
    if not s.biorxiv_days or _CATALOG["loading"] or (time.time() - _CATALOG["loaded_at"] < 24 * 3600 and _CATALOG["items"]):
        return

    async def run():
        _CATALOG["loading"] = True
        http = HttpClient()
        try:
            await _load_catalog(http, s.biorxiv_days)
        finally:
            _CATALOG["loading"] = False
            await http.close()

    try:
        asyncio.get_running_loop().create_task(run())
    except RuntimeError:
        pass


def biorxiv(phrase: str, n: int = 8) -> list[RawDoc]:
    """Препринты bioRxiv/medRxiv из свежего каталога, где все слова фразы есть в названии или аннотации."""
    words = _words(phrase)
    if not words or not _CATALOG["items"]:
        return []
    out = []
    for it in _CATALOG["items"]:
        text = f"{it.get('title', '')} {it.get('abstract', '')}".lower()
        if all(w in text for w in words):
            out.append(RawDoc(url=f"https://doi.org/{it.get('doi')}", title=clean(it.get("title"), 400), snippet=clean(it.get("abstract"), 600),
                              published=it.get("date"), source_name=f"{it.get('server', 'biorxiv')} ({it.get('author_corresponding_institution') or 'препринт'})",
                              source_type="preprint", language="en", collector="biorxiv", extra={"category": it.get("category")}))
    return sorted(out, key=lambda d: d.published or "", reverse=True)[:n]


# ---------------------------------------------------------------- Stack Exchange

SE = "https://api.stackexchange.com/2.3/search/advanced"
SE_SITES = {"software": "stackoverflow", "life_med": "bioinformatics", "materials": "physics", "energy": "engineering"}


async def stackexchange(http: HttpClient, phrase: str, profile: str = "software", n: int = 5) -> tuple[list[RawDoc], int]:
    """Вопросы инженеров с фразой за 2 года на сайте Stack Exchange по профилю запроса: (документы, всего вопросов)."""
    s = get_settings()
    if not s.stackexchange_key:
        return [], 0
    site = SE_SITES.get(profile, "stackoverflow")
    since = int((datetime.now(timezone.utc) - timedelta(days=730)).timestamp()) // 86400 * 86400  # округлено до суток — для кэша
    data = await http.get(SE, params={"q": f'"{phrase.replace(chr(34), "")}"', "site": site, "pagesize": n, "order": "desc", "sort": "relevance", "fromdate": since,
                                      "key": s.stackexchange_key})
    docs = []
    for it in data.get("items") or []:
        title = clean(re.sub(r"&#39;|&quot;", "'", it.get("title") or ""), 300)
        if not title:
            continue
        ts = it.get("creation_date")
        docs.append(RawDoc(url=it.get("link") or "", title=title, snippet=f"Вопрос на {site}.stackexchange: {it.get('answer_count', 0)} ответов, рейтинг {it.get('score', 0)}",
                           published=datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat() if ts else None,
                           source_name=f"Stack Exchange ({site})", source_type="community", language="en", collector="stackexchange"))
    return docs, len(docs) + (1 if data.get("has_more") else 0)
