"""Государственные гранты: NIH RePORTER (США, медицина и биотех), NSF Awards (США, наука и инженерия),
UKRI Gateway to Research (Великобритания). Открытые API без ключа.

Зачем: грант — это деньги, которые государство вкладывает в направление за годы до рынка. Рост числа грантов
по теме — ранний и «твёрдый» признак (за ним стоит экспертиза фонда), а проекты описывают то, что ещё только
исследуется. NIH отдаёт число проектов по годам — это ряд для машины времени.
"""
import re
from datetime import date, datetime, timezone

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient, NotFound

NIH = "https://api.reporter.nih.gov/v2/projects/search"
NSF = "https://api.nsf.gov/services/v1/awards.json"
UKRI = "https://gtr.ukri.org/api/search/project"

# Служебные префиксы заголовков NSF: «Collaborative Research: DMREF: Catalyst Surfaces» — из таких заголовков майнинг фраз
# делал кандидата «dmref catalyst surfaces». Срезаем все префиксы «ПРОГРАММА:» в начале.
NSF_PREFIX = re.compile(r"^(?:(?:collaborative research|rapid|eager|career|conference|travel|rui|mri|i-corps|planning|"
                        r"sbir|sttr|sbir/sttr|sbir phase i{1,2}|sttr phase i{1,2}|sbir/sttr phase i{1,2}|(?-i:[A-Z][A-Z0-9/&\-]{1,15}))\s*:\s*)+", re.I)
SBIR_TITLE = re.compile(r"\b(sbir|sttr)\b", re.I)
SBIR_NIH = re.compile(r"^\d?(R41|R42|R43|R44|U43|U44|SB1)", re.I)  # коды программ малого бизнеса NIH


def strip_program_prefix(title: str) -> tuple[str, bool]:
    """«SBIR Phase I: Low-cost microfluidic assay» → («Low-cost microfluidic assay», True). Второй элемент — грант SBIR/STTR."""
    sbir = bool(SBIR_TITLE.search(title.split(":")[0])) if ":" in title else False
    out = NSF_PREFIX.sub("", title).strip()
    return (out or title), sbir


SBIR_TEXT = "грант SBIR/STTR малому бизнесу — у технологии уже есть компания"


def _nih_criteria(query: str, years: list[int]) -> dict:
    return {"advanced_text_search": {"search_text": f'"{query.replace(chr(34), "")}"', "operator": "and",
                                     "search_field": "projecttitle,abstracttext"}, "fiscal_years": years}


async def nih(http: HttpClient, query: str, years: list[int] | None = None, n: int = 10) -> list[RawDoc]:
    years = years or [date.today().year - k for k in range(3)]
    data = await http.post(NIH, {"criteria": _nih_criteria(query, years), "limit": n, "sort_field": "project_start_date", "sort_order": "desc",
                                 "include_fields": ["ProjectTitle", "FiscalYear", "AwardAmount", "ProjectNum", "Organization", "ProjectStartDate", "ApplId", "AgencyIcAdmin"]})
    docs = []
    for it in data.get("results") or []:
        title = clean(it.get("project_title"), 400)
        if not title or not it.get("appl_id"):
            continue
        org = (it.get("organization") or {}).get("org_name") or ""
        agency = (it.get("agency_ic_admin") or {}).get("abbreviation") or "NIH"
        amount = it.get("award_amount")
        sbir = bool(SBIR_NIH.match(str(it.get("project_num") or "")))
        docs.append(RawDoc(
            url=f"https://reporter.nih.gov/project-details/{it['appl_id']}",
            title=title,
            snippet=clean(f"Грант NIH/{agency}, {org}" + (f", ${int(amount):,}" if amount else "") + (f"; {SBIR_TEXT}" if sbir else "")),
            published=(it.get("project_start_date") or "")[:10] or f"{it.get('fiscal_year')}-01-01",
            source_name=f"NIH RePORTER ({agency})", source_type="grant", language="en", collector="nih",
            extra={"event": "grant", "amount_usd": amount, "org": org, "sbir": sbir},
        ))
    return docs


async def nih_yearly(http: HttpClient, query: str, years: list[int]) -> dict[str, int]:
    """Число проектов NIH по финансовым годам (один запрос на год: API отдаёт общее число в meta.total)."""
    out = {}
    for y in years:
        data = await http.post(NIH, {"criteria": _nih_criteria(query, [y]), "limit": 1, "include_fields": ["ApplId"]})
        out[str(y)] = int((data.get("meta") or {}).get("total") or 0)
    return out


async def nsf(http: HttpClient, query: str, since: date | None = None, n: int = 10) -> list[RawDoc]:
    since = since or date(date.today().year - 2, 1, 1)
    data = await http.get(NSF, params={"keyword": f'"{query.replace(chr(34), "")}"', "rpp": n, "dateStart": since.strftime("%m/%d/%Y"),
                                       "printFields": "id,title,startDate,fundsObligatedAmt,awardeeName"})
    docs = []
    for it in (data.get("response") or {}).get("award") or []:
        title = clean(it.get("title"), 400)
        if not title or not it.get("id"):
            continue
        title, sbir = strip_program_prefix(title)
        try:
            started = datetime.strptime(it.get("startDate", ""), "%m/%d/%Y").date().isoformat()
        except ValueError:
            started = None
        amount = it.get("fundsObligatedAmt")
        docs.append(RawDoc(
            url=f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={it['id']}",
            title=title,
            snippet=clean(f"Грант NSF, {it.get('awardeeName') or ''}" + (f", ${int(float(amount)):,}" if amount else "") + (f"; {SBIR_TEXT}" if sbir else "")),
            published=started, source_name="NSF Awards", source_type="grant", language="en", collector="nsf",
            extra={"event": "grant", "amount_usd": amount, "org": it.get("awardeeName"), "sbir": sbir},
        ))
    return docs


async def ukri(http: HttpClient, query: str, n: int = 10, min_year: int | None = None) -> list[RawDoc]:
    min_year = min_year or date.today().year - 3
    try:
        data = await http.get(UKRI, params={"term": f'"{query.replace(chr(34), "")}"', "page": 1, "fetchSize": max(n * 2, 10)})
    except NotFound:  # UKRI отвечает 404, когда проектов по фразе нет
        return []
    docs = []
    for res in (data.get("facetedSearchResultBean") or {}).get("results") or []:
        comp = res.get("projectComposition") or {}
        p = comp.get("project") or {}
        fund = p.get("fund") or {}
        start = fund.get("start")
        started = datetime.fromtimestamp(start / 1000, tz=timezone.utc).date() if start else None
        if not p.get("title") or not p.get("id") or (started and started.year < min_year):
            continue
        funder = (fund.get("funder") or {}).get("name") or "UKRI"
        org = (comp.get("leadResearchOrganisation") or {}).get("name") or ""
        docs.append(RawDoc(
            url=f"https://gtr.ukri.org/projects?ref={p.get('grantReference') or p['id']}",
            title=clean(p["title"], 400),
            snippet=clean(f"Грант UKRI/{funder} ({p.get('grantCategory') or 'проект'}), {org}. {p.get('abstractText') or ''}"),
            published=started.isoformat() if started else None,
            source_name=f"UKRI Gateway to Research ({funder})", source_type="grant", language="en", collector="ukri",
            extra={"event": "grant", "amount_gbp": fund.get("valuePounds"), "org": org},
        ))
    return docs[:n]
