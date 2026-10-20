"""Рыночные и регуляторные источники для лестницы «от науки до рынка» (официальные API и ленты, подключены 20.10):

- ClinicalTrials.gov API v2 (без ключа): клинические исследования — ступень «пилот / испытания» для медицины и биотеха;
- SEC EDGAR, полнотекстовый поиск (без ключа, обязателен User-Agent с почтой, до 10 запросов/с): форма D — уведомление о
  привлечении средств (ступень «раунд»), отчёты 8-K / 10-K / S-1 — публичная компания пишет о технологии (ступень «серийный продукт»).
  Внимание: заявленный размер размещения и фактически привлечённая сумма — разные показатели;
- Роспатент, поисковая платформа (ключ ROSPATENT_API_KEY): российские патенты — ступень «патент» и окно «Россия»;
- ЕИС госзакупок, RSS-лента поиска (без ключа и подписи): закупки — ступень «закупка в России».
"""
import re
from datetime import date, timedelta
from xml.etree import ElementTree as ET  # noqa: N817 — разбор RSS из официальной ленты ЕИС

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient
from app.config import get_settings

# ---------------------------------------------------------------- ClinicalTrials.gov

CT = "https://clinicaltrials.gov/api/v2/studies"


async def clinical_trials(http: HttpClient, phrase: str, n: int = 6, years: int = 3) -> tuple[list[RawDoc], int]:
    """Исследования с фразой, начатые или обновлённые за years лет: (документы, всего найдено)."""
    since = (date.today() - timedelta(days=365 * years)).isoformat()
    data = await http.get(CT, params={"query.term": phrase, "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},MAX]", "pageSize": n,
                                      "format": "json", "countTotal": "true",
                                      "fields": "NCTId,BriefTitle,Phase,OverallStatus,LeadSponsorName,StartDate,LastUpdatePostDate"})
    docs = []
    for st in data.get("studies") or []:
        ps = st.get("protocolSection") or {}
        idm, stm = ps.get("identificationModule") or {}, ps.get("statusModule") or {}
        nct, title = idm.get("nctId"), clean(idm.get("briefTitle"), 400)
        if not nct or not title:
            continue
        phases = ", ".join((ps.get("designModule") or {}).get("phases") or []) or "фаза не указана"
        sponsor = ((ps.get("sponsorCollaboratorsModule") or {}).get("leadSponsor") or {}).get("name") or ""
        start = (stm.get("startDateStruct") or {}).get("date") or ""
        docs.append(RawDoc(url=f"https://clinicaltrials.gov/study/{nct}", title=title,
                           snippet=clean(f"Клиническое исследование {nct}: {phases}, статус {stm.get('overallStatus', '')}, спонсор {sponsor}", 400),
                           published=(start + "-01")[:10] if re.match(r"\d{4}-\d{2}", start) else None,
                           source_name="ClinicalTrials.gov", source_type="trial", language="en", collector="clinicaltrials",
                           extra={"event": "launch", "market": "pilot", "sponsor": sponsor, "phase": phases}))
    return docs, int(data.get("totalCount") or len(docs))


# ---------------------------------------------------------------- SEC EDGAR

EFTS = "https://efts.sec.gov/LATEST/search-index"


async def sec_filings(http: HttpClient, phrase: str, n: int = 6, years: int = 2) -> tuple[list[RawDoc], dict]:
    """Документы EDGAR с точной фразой за years лет: форма D (раунд), 8-K / 10-K / S-1 (публичная компания о технологии)."""
    s = get_settings()
    if not s.sec_user_agent:  # без User-Agent с почтой SEC отвечает 403 — не тратим время прогона
        return [], {"total": 0, "by_form": {}}
    end = date.today()
    data = await http.get(EFTS, params={"q": f'"{phrase.replace(chr(34), "")}"', "forms": "D,S-1,8-K,10-K", "dateRange": "custom",
                                        "startdt": (end - timedelta(days=365 * years)).isoformat(), "enddt": end.isoformat()},
                          headers={"User-Agent": s.sec_user_agent, "Accept-Encoding": "gzip, deflate"})
    hits = (data.get("hits") or {}).get("hits") or []
    docs, by_form = [], {}
    for h in hits:
        src = h.get("_source") or {}
        form = src.get("form") or src.get("root_form") or ""
        by_form[form] = by_form.get(form, 0) + 1
        if len(docs) >= n:
            continue
        name = re.sub(r"\s*\(CIK \d+\)", "", ", ".join(src.get("display_names") or [])) or "компания"
        adsh = (src.get("adsh") or h.get("_id", "").split(":")[0]).replace("-", "")
        cik = ((src.get("ciks") or [""])[0]).lstrip("0")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/" if cik and adsh else "https://efts.sec.gov/LATEST/search-index"
        is_d = form.startswith("D")
        docs.append(RawDoc(url=url, title=f"{name}: форма {form}", source_name="SEC EDGAR", source_type="filing", language="en", collector="sec",
                           snippet=("Уведомление о привлечении средств (форма D)" if is_d else f"Публичная компания упоминает технологию в отчёте {form}"),
                           published=src.get("file_date"),
                           extra={"event": "funding" if is_d else "launch", "market": "funding" if is_d else "launch", "company": name}))
    return docs, {"total": int(((data.get("hits") or {}).get("total") or {}).get("value") or len(hits)), "by_form": by_form}


# ---------------------------------------------------------------- Lens.org (патенты)

LENS = "https://api.lens.org/patent/search"


async def lens_patents(http: HttpClient, phrase: str, n: int = 5, years: int = 3) -> tuple[list[RawDoc], int]:
    """Патенты всего мира (Lens.org) с фразой в названии или реферате за years лет: настоящие названия изобретений и
    заявители — ступень «патент» лестницы и компании на карте игроков. (документы, всего найдено)"""
    s = get_settings()
    if not s.lens_api_token:
        return [], 0
    since = date(date.today().year - years, 1, 1).isoformat()
    body = {"query": {"bool": {"must": [{"query_string": {"query": f'"{phrase.replace(chr(34), "")}"', "fields": ["title", "abstract"]}},
                                        {"range": {"date_published": {"gte": since}}}]}},
            "size": n, "sort": [{"date_published": "desc"}],
            "include": ["lens_id", "biblio.invention_title", "date_published", "biblio.parties.applicants", "jurisdiction", "doc_number", "kind"]}
    data = await http.post(LENS, body, headers={"Authorization": f"Bearer {s.lens_api_token}"})
    docs = []
    for it in data.get("data") or []:
        titles = (it.get("biblio") or {}).get("invention_title") or []
        title = next((t.get("text") for t in titles if t.get("lang") == "en"), None) or (titles[0].get("text") if titles else "")
        if not title or not it.get("lens_id"):
            continue
        apps = [((a.get("extracted_name") or {}).get("value") or "").strip() for a in ((it.get("biblio") or {}).get("parties") or {}).get("applicants") or []]
        apps = [a for a in apps if a][:3]
        number = f"{it.get('jurisdiction', '')}{it.get('doc_number', '')}{it.get('kind', '')}"
        docs.append(RawDoc(url=f"https://www.lens.org/lens/patent/{it['lens_id']}", title=clean(title.capitalize() if title.isupper() else title, 400),
                           snippet=clean(f"Патент {number}; заявитель: {', '.join(apps) or 'не указан'}", 400), published=(it.get("date_published") or "")[:10] or None,
                           source_name=f"Lens.org ({it.get('jurisdiction') or 'патент'})", source_type="patent", language="en", collector="lens",
                           extra={"event": "patent", "market": "patent", "holder": ", ".join(apps), "applicants": apps, "country": it.get("jurisdiction")}))
    return docs, int(data.get("total") or len(docs))


# ---------------------------------------------------------------- Роспатент

RP = "https://searchplatform.rospatent.gov.ru/patsearch/v0.2/search"


async def rospatent(http: HttpClient, phrase: str, n: int = 6, since_year: int | None = None) -> tuple[list[RawDoc], int]:
    """Российские патентные документы с фразой (русской или английской) с since_year: (документы, всего найдено)."""
    s = get_settings()
    if not s.rospatent_api_key:
        return [], 0
    since_year = since_year or date.today().year - 5
    body = {"q": phrase, "limit": n, "sort": "publication date:desc", "datasets": ["ru_since_1994"],
            "filter": {"date_published": {"range": {"gte": f"{since_year}0101"}}}}
    data = await http.post(RP, body, headers={"Authorization": f"Bearer {s.rospatent_api_key}"})
    docs = []
    for h in data.get("hits") or []:
        bib = (h.get("biblio") or {}).get("ru") or (h.get("biblio") or {}).get("en") or {}
        title = clean(bib.get("title") or h.get("snippet", {}).get("title") or "", 400)
        cm = h.get("common") or {}
        doc_id = h.get("id") or ""
        if not title:
            continue
        pub = cm.get("publication_date") or ""
        appl = ", ".join(p.get("name", "") for p in (bib.get("patentee") or bib.get("applicant") or [])[:2])
        docs.append(RawDoc(url=f"https://searchplatform.rospatent.gov.ru/doc/{doc_id}" if doc_id else "https://searchplatform.rospatent.gov.ru/",
                           title=title, snippet=clean(f"Патент РФ {cm.get('document_number', '')} {cm.get('kind', '')}; правообладатель: {appl}. "
                                                      + re.sub(r"<[^>]+>|&lt;/?em&gt;", "", (h.get("snippet") or {}).get("description") or ""), 600),
                           published=f"{pub[:4]}-{pub[5:7]}-{pub[8:10]}" if re.match(r"\d{4}\.\d{2}\.\d{2}", pub) else (pub[:10] or None),
                           source_name="Роспатент", source_type="patent", language="ru", collector="rospatent",
                           extra={"event": "patent", "market": "patent", "holder": appl}))
    return docs, int(data.get("total") or len(docs))


# ---------------------------------------------------------------- ЕИС госзакупок

EIS = "https://zakupki.gov.ru/epz/order/extendedsearch/rss.html"


def _rss_items(text: str) -> list[dict]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    out = []
    for it in root.iter("item"):
        out.append({k: (it.findtext(k) or "").strip() for k in ("title", "link", "description", "pubDate")})
    return out


async def procurement(http: HttpClient, phrase_ru: str, n: int = 10) -> list[RawDoc]:
    """Закупки ЕИС (44-ФЗ и 223-ФЗ), где встречается русское название технологии (с морфологией)."""
    text = await http.get(EIS, params={"searchString": phrase_ru, "morphology": "on", "sortBy": "UPDATE_DATE", "sortDirection": "false",
                                       "fz44": "on", "fz223": "on", "recordsPerPage": "_10"}, as_json=False)
    from email.utils import parsedate_to_datetime

    docs = []
    for it in _rss_items(text)[:n]:
        desc = clean(re.sub(r"<[^>]+>", " ", it["description"]), 600)
        try:
            pub = parsedate_to_datetime(it["pubDate"]).date().isoformat() if it["pubDate"] else None
        except (TypeError, ValueError):
            pub = None
        if not it["title"] or not it["link"]:
            continue
        link = it["link"] if it["link"].startswith("http") else f"https://zakupki.gov.ru{it['link']}"
        docs.append(RawDoc(url=link, title=clean(it["title"], 400), snippet=desc, published=pub, source_name="ЕИС госзакупок",
                           source_type="procurement", language="ru", collector="zakupki", extra={"event": "procurement", "market": "procurement"}))
    return docs
