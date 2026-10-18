"""Википедия как индикатор массовой известности: есть ли статья и сколько у неё просмотров.

Устоявшаяся статья с большим трафиком — признак зрелой, общеизвестной технологии.
"""
import re
from datetime import date, timedelta
from urllib.parse import quote

from app.collectors.http import HttpClient

SEARCH = "https://en.wikipedia.org/w/api.php"
VIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{title}/monthly/{start}/{end}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


async def lookup(http: HttpClient, phrase: str, as_of: date | None = None) -> dict:
    """{'exists': bool, 'title': str|None, 'monthly_views': float}

    as_of — дата среза: просмотры берутся за год до неё; статья считается существовавшей, если у неё были просмотры
    (иначе статья, написанная после среза, «протекла» бы в прошлое)."""
    data = await http.get(
        SEARCH,
        params={"action": "query", "list": "search", "srsearch": f'intitle:"{phrase}"', "srlimit": 3, "format": "json"},
    )
    hits = (data.get("query") or {}).get("search", [])
    target = _norm(phrase)
    title = None
    for h in hits:
        t = _norm(h.get("title", ""))
        if t == target or t.rstrip("s") == target.rstrip("s"):
            title = h["title"]
            break
    if not title:
        return {"exists": False, "title": None, "monthly_views": 0.0}
    end = (as_of or date.today()).replace(day=1) - timedelta(days=1)
    start = (end - timedelta(days=365)).replace(day=1)
    try:
        v = await http.get(
            VIEWS.format(title=quote(title.replace(" ", "_"), safe=""), start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
        )
        items = v.get("items", [])
        views = sum(i.get("views", 0) for i in items) / max(len(items), 1)
    except Exception:
        views = 0.0
    if as_of and views == 0:
        return {"exists": False, "title": None, "monthly_views": 0.0}
    return {"exists": True, "title": title, "monthly_views": views}
