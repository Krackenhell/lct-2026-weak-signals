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
    "api.crossref.org": 0.2,
    "cyberleninka.ru": 1.0,
    "www.ebi.ac.uk": 0.2,
    "api.semanticscholar.org": 1.1,
    # RSS-ленты изданий: вежливый темп (лента читается один раз за запуск, дальше — из кэша)
    "siliconangle.com": 1.5,
    "techcrunch.com": 1.0,
    "www.theblock.co": 1.0,
    "www.prnewswire.com": 1.0,
    "vc.ru": 1.0,
    "www.cnews.ru": 1.0,
    "technode.com": 1.0,
    "pandaily.com": 1.0,
    "www.scmp.com": 1.0,
    "www.36kr.com": 1.0,
    "www.ithome.com": 1.0,
    "www.cnbeta.com.tw": 1.0,
    "www.infoq.cn": 1.0,
    "api.reporter.nih.gov": 1.0,  # NIH просит не чаще 1 запроса в секунду
    "api.nsf.gov": 0.3,
    "gtr.ukri.org": 0.5,
    "huggingface.co": 0.5,
    "api2.openreview.net": 0.5,
}


BREAKER_COOLDOWN = 60.0
# Источники, которые при перегрузке почти никогда не восстанавливаются за секунды: повторять бессмысленно,
# каждый повтор — это 5–15 секунд ожидания в запросе аналитика.
HOST_RETRIES = {"api.gdeltproject.org": 1}
MAX_WAIT = 15.0  # секунд: дольше по Retry-After внутри запроса не ждём


def _retry_after(resp: httpx.Response) -> float | None:
    try:
        return min(max(float(resp.headers["retry-after"]), 1.0), 60.0)
    except (KeyError, ValueError):
        return None


class SourceError(Exception):
    pass


class NotFound(SourceError):
    pass


# Состояние ограничителя частоты общее для всех запусков в процессе: несколько
# одновременных запросов жюри не должны вместе превышать лимиты источников.
_LOCKS: dict[str, asyncio.Lock] = {}
_LAST: dict[str, float] = {}


class HttpClient:
    def __init__(self, patient: bool = False) -> None:
        """patient=True — для пакетных задач (обучение, ретроспективная проверка): ждём, сколько просит источник,
        и не отключаем его после лимита. Пропущенный источник испортил бы обучающие данные, а спешить там некуда."""
        self.patient = patient
        s = get_settings()
        self._client = httpx.AsyncClient(
            timeout=s.http_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self._locks = _LOCKS
        self._last = _LAST
        self._cache_dir = Path(s.cache_dir)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        self._ttl = s.cache_ttl_hours * 3600
        # Поиск GitHub без токена: 10 запросов/мин, с токеном: 30 запросов/мин.
        self._interval = {**HOST_INTERVAL, "api.github.com": 2.2 if s.github_token else 6.5}
        self.stats: dict[str, dict[str, int]] = {}
        # Предохранитель: после 3 неудач подряд источник пропускается BREAKER_COOLDOWN секунд,
        # чтобы недоступный сервис не съедал время обработки, но и не выпадал до конца запроса.
        self._fails: dict[str, int] = {}
        self._open_until: dict[str, float] = {}

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

    async def post(self, url: str, body: dict, headers: dict | None = None, retries: int = 3, cache: bool = True) -> Any:
        """POST с JSON-телом (КиберЛенинка): тот же кэш, повторы, ограничение частоты и предохранитель, что у GET."""
        return await self.get(url, headers=headers, retries=retries, cache=cache, json_body=body)

    async def get(
        self,
        url: str,
        params: dict | None = None,
        headers: dict | None = None,
        as_json: bool = True,
        retries: int = 3,
        cache: bool = True,
        json_body: dict | None = None,
    ) -> Any:
        host = urlparse(url).netloc
        retries = max(retries, 5) if self.patient else min(retries, HOST_RETRIES.get(host, retries))
        path = self._cache_path(url, params if json_body is None else {"__post__": json_body, **(params or {})})
        if cache and path.exists() and time.time() - path.stat().st_mtime < self._ttl:
            self._bump(host, "cached")
            return json.loads(path.read_text(encoding="utf-8"))

        if self._fails.get(host, 0) >= 3 and not self.patient:
            if time.monotonic() < self._open_until.get(host, 0.0):
                self._bump(host, "failed")
                raise SourceError(f"{host} временно отключён после серии сбоев")
            # Пауза прошла: один пробный запрос без повторов, параллельные запросы ждут его исхода.
            self._open_until[host] = time.monotonic() + BREAKER_COOLDOWN
            retries = 1
        last_exc: Exception | None = None
        for attempt in range(retries):
            await self._throttle(host)
            backoff = 1.5 * (attempt + 1) + self._interval.get(host, 0)
            try:
                if json_body is None:
                    resp = await self._client.get(url, params=params, headers=headers)
                else:
                    resp = await self._client.post(url, params=params, headers=headers, json=json_body)
                if resp.status_code == 403 and resp.headers.get("x-ratelimit-remaining") == "0":
                    # Лимит GitHub: ждём сброса окна (не более минуты) и пробуем снова.
                    reset = float(resp.headers.get("x-ratelimit-reset", time.time() + 30))
                    await asyncio.sleep(min(max(reset - time.time(), 1), 65))
                    raise SourceError("rate limit, waited for reset")
                if resp.status_code == 429 and params and "api_key" in params:
                    # Дневной бюджет ключа исчерпан — продолжаем в анонимной квоте источника.
                    params = {k: v for k, v in params.items() if k != "api_key"}
                    raise SourceError("HTTP 429 (ключ исчерпан, переход на анонимную квоту)")
                if resp.status_code == 429 or resp.status_code >= 500:
                    if resp.status_code == 429:
                        # Лимит частоты: ждём, сколько просит источник, но не больше MAX_WAIT — дольше ждать внутри
                        # запроса аналитика бессмысленно, остальные источники работают (найдено замером: 2 × 60 с).
                        ra = _retry_after(resp)
                        if ra and ra > MAX_WAIT and not self.patient:
                            last_exc = SourceError(f"HTTP 429 (повтор через {ra:.0f} с — пропускаем)")
                            break
                        backoff = ra or (20.0 if self.patient else 5.0) * (attempt + 1)
                    raise SourceError(f"HTTP {resp.status_code}")
                if resp.status_code >= 400:
                    # Ошибка запроса (например, 404): источник исправен, повторять бессмысленно.
                    self._bump(host, "failed")
                    self._fails[host] = 0
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
                if attempt < retries - 1:
                    await asyncio.sleep(backoff)
        self._bump(host, "failed")
        self._fails[host] = self._fails.get(host, 0) + 1
        if "HTTP 429" in str(last_exc) and not self.patient:
            # Лимит частоты не снят даже после повторов: следующие запросы к источнику тоже упрутся в него.
            # Сразу отключаем источник на время охлаждения, чтобы не тратить минуты запроса на ожидание.
            self._fails[host] = max(self._fails[host], 3)
        if self._fails[host] >= 3:
            self._open_until[host] = time.monotonic() + BREAKER_COOLDOWN
        safe = {k: ("***" if "key" in k or "token" in k else v) for k, v in (params or {}).items()}
        log.warning("source failed %s %s: %s", url, safe, last_exc)
        raise SourceError(str(last_exc))
