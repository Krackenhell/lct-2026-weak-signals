import asyncio

from app.collectors.base import RawDoc
from app.pipeline.live import LiveFeed
from app.pipeline import discovery
from app.config import get_settings


def doc(n: int, **kwargs):
    return RawDoc(title=f"Publication {n}", url=f"https://example.org/{n}", source_name="arXiv", source_type="preprint", **kwargs)


def test_feed_bounded_unique_and_safe():
    feed = LiveFeed(limit=3)
    snapshot = feed.add([doc(i) for i in range(8)])
    assert snapshot["total"] == 8
    assert [d["id"] for d in snapshot["documents"]] == [6, 7, 8]
    assert snapshot["source_count"] == 1
    feed.add([doc(0), RawDoc(title="Unsafe", url="javascript:alert(1)", source_name="X")])
    assert len(feed.seen) == 8  # dedup survives eviction from the visible window
    feed.add([doc(9)])
    assert snapshot["documents"][-1]["title"] == "Publication 7"  # immutable snapshot
    assert "snippet" not in snapshot["documents"][0]


def test_completed_source_is_published_before_slow_source(monkeypatch):
    settings = get_settings()
    for option in ("extra_sources", "news_sources", "grant_sources", "ml_sources", "startup_sources", "more_sources"):
        monkeypatch.setattr(settings, option, False)

    async def check():
        released = asyncio.Event()
        batches = []

        async def fast(*args, **kwargs):
            return [doc(1)]

        async def slow(*args, **kwargs):
            await asyncio.wait_for(released.wait(), 2)
            return [doc(2)]

        async def empty(*args, **kwargs):
            return []

        async def hn(*args, **kwargs):
            return [], {}

        async def on_batch(batch):
            batches.extend(d.title for d in batch)
            released.set()

        monkeypatch.setattr(discovery.arxiv, "search", fast)
        monkeypatch.setattr(discovery.openalex, "search", slow)
        monkeypatch.setattr(discovery.gdelt, "search", empty)
        monkeypatch.setattr(discovery.hackernews, "search", hn)
        result = await discovery.build_corpus(None, {"subqueries": ["test"], "topic_en": ""}, on_batch=on_batch)
        assert batches[0] == "Publication 1"
        assert {d.title for d in result} == {"Publication 1", "Publication 2"}

    asyncio.run(check())
