"""Bounded, public metadata for the search radar; no snippets or model prompts."""
from datetime import datetime, timezone
from urllib.parse import urlsplit

from app.collectors.base import RawDoc


class LiveFeed:
    def __init__(self, limit: int = 60):
        self.limit = limit
        self.seen: set[str] = set()
        self.sources: set[str] = set()
        self.documents: list[dict] = []

    def add(self, batch: list[RawDoc]) -> dict:
        for doc in batch:
            key = doc.title.strip().lower()[:90]
            try:
                url = urlsplit(doc.url)
            except ValueError:
                continue
            if not key or key in self.seen or url.scheme not in ("http", "https") or not url.hostname:
                continue
            self.seen.add(key)
            self.sources.add(doc.source_name)
            self.documents.append({
                "id": len(self.seen),
                "title": doc.title[:400],
                "url": doc.url[:2000],
                "source_name": doc.source_name[:200],
                "source_type": doc.source_type,
                "published": doc.published,
                "found_at": datetime.now(timezone.utc).isoformat(),
            })
        self.documents = self.documents[-self.limit:]
        return {
            "total": len(self.seen),
            "source_count": len(self.sources),
            "sources": sorted(self.sources)[:40],
            "documents": list(self.documents),
        }
