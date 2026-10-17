"""Поиск по отраслевым новостям: Google News (EN и RU) и SiliconANGLE.

Зачем: 87% ссылок в 100 сигналах организатора — сайты компаний, стартап-издания и СМИ, а в обоснованиях
слова «раунд / seed / Series A/B» встречаются 112 раз. Научные индексы такие события не видят.

Google News отдаёт публичную RSS-ленту поиска без ключа: заголовок, дату и издание (поле source). Ссылка ведёт
на страницу перехода Google, поэтому издание и его домен сохраняются отдельно — по ним считаются доверие
и независимость подтверждений. SiliconANGLE (WordPress) отдаёт RSS поиска по своему архиву.
"""
import re
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

GOOGLE = "https://news.google.com/rss/search?q={q}&hl={hl}&gl={gl}&ceid={gl}:{lang}"
SILICONANGLE = "https://siliconangle.com/?s={q}&feed=rss2"

# События финансирования и выхода на рынок: самое «твёрдое» свидетельство для слабого сигнала по версии датасета.
FUNDING = re.compile(
    r"\braise[sd]?\b|\braising\b|\bseries [a-e]\b|\bseed (round|funding)\b|\bpre-seed\b|\bfunding round\b|\bsecures? \$|"
    r"\b\$\d[\d.,]*\s?(m|mn|million|b|bn|billion)\b|\bbacked by\b|\bacquires?\b|\bacquisition\b|"
    r"привлек\w*|раунд|инвестиц\w*|посевн\w*|сделк\w*|поглощ\w*|приобрет\w*",
    re.I,
)
LAUNCH = re.compile(r"\blaunch(es|ed)?\b|\bunveil(s|ed)?\b|\brolls? out\b|\bpilot\b|запуска\w*|запусти\w*|представил\w*|пилот\w*", re.I)


def event_of(text: str) -> str | None:
    """Тип события в заголовке новости: раунд или сделка, запуск или пилот, иначе None."""
    if FUNDING.search(text or ""):
        return "funding"
    if LAUNCH.search(text or ""):
        return "launch"
    return None


def _date(s: str | None) -> str | None:
    try:
        return parsedate_to_datetime(s).date().isoformat() if s else None
    except (TypeError, ValueError):
        return None


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _strip_publisher(title: str, publisher: str) -> str:
    # Google News добавляет издание в конец заголовка: «Stripe agentic commerce revs up - Payments Dive».
    if publisher and title.endswith(" - " + publisher):
        return title[: -len(publisher) - 3]
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", title) if " - " in title else title


async def google_news(http: HttpClient, query: str, lang: str = "en", n: int = 20) -> list[RawDoc]:
    hl, gl = ("ru", "RU") if lang == "ru" else ("en-US", "US")
    text = await http.get(GOOGLE.format(q=quote(query.replace('"', "")), hl=hl, gl=gl, lang=lang), as_json=False)
    feed = feedparser.parse(text)
    docs = []
    for e in feed.entries[:n]:
        src = e.get("source") or {}
        publisher = clean(src.get("title") or "", 120)
        pub_url = src.get("href") or ""
        title = clean(_strip_publisher(e.get("title", ""), publisher), 400)
        if not title:
            continue
        docs.append(
            RawDoc(
                url=e.get("link", ""),
                title=title,
                snippet="",
                published=_date(e.get("published")),
                source_name=publisher or "Google News",
                source_type="news",
                language=lang,
                collector="googlenews",
                extra={"publisher_domain": _domain(pub_url), "event": event_of(title), "via": "Google News"},
            )
        )
    return [d for d in docs if d.url]


async def siliconangle(http: HttpClient, query: str, n: int = 20) -> list[RawDoc]:
    text = await http.get(SILICONANGLE.format(q=quote(query.replace('"', "")).replace("%20", "+")), as_json=False)
    feed = feedparser.parse(text)
    docs = []
    for e in feed.entries[:n]:
        title = clean(e.get("title"), 400)
        if not title:
            continue
        snippet = clean(re.sub(r"<[^>]+>", " ", e.get("summary", "")), 800)
        docs.append(
            RawDoc(
                url=re.sub(r"\?utm_.*$", "", e.get("link", "")),
                title=title,
                snippet=snippet,
                published=_date(e.get("published")),
                source_name="SiliconANGLE",
                source_type="news",
                language="en",
                collector="siliconangle",
                extra={"publisher_domain": "siliconangle.com", "event": event_of(f"{title} {snippet}")},
            )
        )
    return [d for d in docs if d.url]
