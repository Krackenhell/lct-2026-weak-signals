"""Хабр (RSS поиска): русскоязычное профессиональное IT-сообщество, в т.ч. корпоративные блоги компаний."""
import re
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

RSS = "https://habr.com/ru/rss/search/?q={q}&target_type=posts&order=relevance"


def _date(s: str | None) -> str | None:
    try:
        return parsedate_to_datetime(s).date().isoformat() if s else None
    except (TypeError, ValueError):
        return None


async def search(http: HttpClient, query: str, n: int = 15) -> list[RawDoc]:
    text = await http.get(RSS.format(q=quote(query)), as_json=False)
    feed = feedparser.parse(text)
    docs = []
    for e in feed.entries[:n]:
        link = re.sub(r"\?utm_.*$", "", e.get("link", ""))
        is_company = "/companies/" in link
        docs.append(
            RawDoc(
                url=link,
                title=clean(e.get("title"), 400),
                snippet=clean(re.sub(r"<[^>]+>", " ", e.get("description", "")), 800),
                published=_date(e.get("published")),
                source_name="Хабр" + (" (блог компании)" if is_company else ""),
                source_type="news" if not is_company else "press",
                language="ru",
                collector="habr",
            )
        )
    return [d for d in docs if d.title]
