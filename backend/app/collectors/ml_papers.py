"""Ранние исследования в ИИ: Hugging Face Papers и OpenReview. Открытые API без ключа.

Hugging Face Papers — статьи, которые обсуждает ML-сообщество (голоса, ключевые слова); заменил закрытый
в 2025 году Papers with Code. OpenReview — статьи, поданные на ICLR, NeurIPS, ICML и их воркшопы:
часть из них появляется там раньше, чем в журналах и индексах (тема ещё на рецензии).
"""
from datetime import datetime, timezone

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

HF = "https://huggingface.co/api/papers/search"
OPENREVIEW = "https://api2.openreview.net/notes/search"


async def hf_papers(http: HttpClient, query: str, n: int = 10, min_year: int | None = None) -> list[RawDoc]:
    data = await http.get(HF, params={"q": query.replace('"', "")})
    docs = []
    for row in data if isinstance(data, list) else []:
        p = row.get("paper") or {}
        title = clean(p.get("title") or row.get("title"), 400)
        published = (p.get("publishedAt") or row.get("publishedAt") or "")[:10] or None
        if not title or not p.get("id") or (min_year and published and int(published[:4]) < min_year):
            continue
        kw = p.get("ai_keywords") if isinstance(p.get("ai_keywords"), list) else []
        docs.append(RawDoc(
            url=f"https://huggingface.co/papers/{p['id']}",
            title=title,
            snippet=clean(p.get("summary") or row.get("summary") or "", 800),
            published=published, source_name="Hugging Face Papers", source_type="preprint", language="en", collector="hfpapers",
            extra={"upvotes": p.get("upvotes"), "keywords": kw[:8], "arxiv_id": p["id"]},
        ))
    docs.sort(key=lambda d: d.published or "", reverse=True)
    return docs[:n]


def _value(content: dict, key: str):
    v = content.get(key)
    return v.get("value") if isinstance(v, dict) else v


async def openreview(http: HttpClient, query: str, n: int = 10, min_year: int | None = None) -> list[RawDoc]:
    data = await http.get(OPENREVIEW, params={"term": query.replace('"', ""), "limit": max(n * 2, 10), "source": "forum"})
    docs = []
    for note in data.get("notes") or []:
        c = note.get("content") or {}
        title = clean(_value(c, "title"), 400)
        ts = note.get("pdate") or note.get("odate") or note.get("cdate")
        published = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).date().isoformat() if ts else None
        if not title or not note.get("id") or (min_year and published and int(published[:4]) < min_year):
            continue
        docs.append(RawDoc(
            url=f"https://openreview.net/forum?id={note['id']}",
            title=title,
            snippet=clean(_value(c, "TLDR") or _value(c, "abstract") or "", 800),
            published=published, source_name=f"OpenReview ({clean(_value(c, 'venue') or note.get('domain') or '', 120)})",
            source_type="preprint", language="en", collector="openreview",
            extra={"venue": _value(c, "venue"), "keywords": (_value(c, "keywords") or [])[:8]},
        ))
    docs.sort(key=lambda d: d.published or "", reverse=True)
    return docs[:n]
