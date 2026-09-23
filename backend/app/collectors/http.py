"""Общий HTTP-клиент сборщиков: дисковый кэш, повторы, ограничение частоты по хостам.

Отказоустойчивость: любой сбой источника превращается в пустой результат и запись
в журнал, а не в падение всего запроса.
"""
import asyncio
import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

USER_AGENT = "weak-signals-lct2026/0.1 (research prototype; +https://github.com/Krackenhell/lct-2026-weak-signals)"

# Минимальный интервал между запросами к хосту (секунды) — по правилам API источников.
HOST_INTERVAL = {
    "export.arxiv.org": 3.1,
    "api.gdeltproject.org": 5.5,
    "api.github.com": 2.2,
    "api.openalex.org": 0.15,
    "hn.algolia.com": 0.2,
}


class SourceError(Exception):
    pass


class NotFound(SourceError):
    pass


class HttpClient:
    def __init__(self) -> None:
        s = get_settings()
        self._client = httpx.AsyncClient(
            timeout=s.http_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._locks: dict[str, asyncio.Lock] = {}
        self._last: dict[str, float] = {}
        self._cache_dir = Path(s.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ttl = s.cache_ttl_hours * 3600
        # Поиск GitHub без токена: 10 запросов/мин, с токеном: 30 запросов/мин.
        self._interval = {**HOST_INTERVAL, "api.github.com": 2.2 if s.github_token else 6.5}
        self.stats: dict[str, dict[str, int]] = {}
        # Предохранитель: после 3 неудач подряд источник пропускается до конца запроса,
        # чтобы недоступный сервис не съедал время обработки.
        self._fails: dict[str, int] = {}

    async def close(self) -> None:
        await self._client.aclose()

    def _bump(self, host: str, key: str) -> None:
        self.stats.setdefault(host, {"ok": 0, "cached": 0, "failed": 0})[key] += 1

    def _cache_path(self, url: str, params: dict | None) -> Path:
        raw = url + json.dumps(params or {}, sort_keys=True, ensure_ascii=False)
        return self._cache_dir / (hashlib.sha1(raw.encode()).hexdigest() + ".json")

    async def _throttle(self, host: str) -> None:
        interval = self._interval.get(host, 0.0)
        if not interval:
            return
        lock = self._locks.setdefault(host, asyncio.Lock())
        async with lock:
            wait = self._last.get(host, 0.0) + interval - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last[host] = time.monotonic()

    async def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        as_json: bool = True,
        retries: int = 3,
        cache: bool = True,
    ) -> Any:
        host = urlparse(url).netloc
        path = self._cache_path(url, params)
        if cache and path.exists() and time.time() - path.stat().st_mtime < self._ttl:
            self._bump(host, "cached")
            return json.loads(path.read_text(encoding="utf-8"))

        if self._fails.get(host, 0) >= 3:
            self._bump(host, "failed")
            raise SourceError(f"{host} временно отключён после серии сбоев")
        last_exc: Exception | None = None
        for attempt in range(retries):
            await self._throttle(host)
            try:
                resp = await self._client.get(url, params=params, headers=headers)
                if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
                    # Лимит GitHub: ждём сброса окна (не более минуты) и пробуем снова.
                    reset = float(resp.headers.get("x-ratelimit-reset", time.time() + 30))
                    await asyncio.sleep(min(max(reset - time.time(), 1), 65))
                    raise SourceError("rate limit, waited for reset")
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise SourceError(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    # Ошибка запроса (например, 404): источник исправен, повторять бессмысленно.
                    self._bump(host, "failed")
                    raise NotFound(f"HTTP {resp.status_code}")
                if as_json:
                    try:
                        data = resp.json()
                    except ValueError as exc:  # GDELT отвечает текстом при превышении лимита
                        raise SourceError(f"not JSON: {resp.text[:120]}") from exc
                else:
                    data = resp.text
                if cache:
                    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                self._bump(host, "ok")
                self._fails[host] = 0
                return data
            except NotFound:
                raise
            except (httpx.HTTPError, SourceError) as exc:
                last_exc = exc
                await asyncio.sleep(1.5 * (attempt + 1) + self._interval.get(host, 0))
        self._bump(host, "failed")
        self._fails[host] = self._fails.get(host, 0) + 1
        log.warning("source failed %s %s: %s", url, params, last_exc)
        raise SourceError(str(last_exc))
