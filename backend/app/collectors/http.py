"""Общий HTTP-клиент сборщиков: дисковый кэш, повторы, ограничение частоты по хостам.

Отказоустойчивость: любой сбой источника превращается в пустой результат и запись
в журнал, а не в падение всего запроса.
"""
import asyncio
import hashlib
import json
import logging
import os
import ssl
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import get_settings

log = logging.getLogger(__name__)

CA_BUNDLE = Path(__file__).resolve().parents[1] / "certs" / "russian_trusted_ca.pem"


def ssl_context() -> ssl.SSLContext:
    """Стандартные корневые сертификаты + УЦ Минцифры (Russian Trusted Root/Sub CA): без него Python не открывает
    zakupki.gov.ru и GigaChat, а отключать проверку сертификатов (verify=False) небезопасно."""
    import certifi

    ctx = ssl.create_default_context(cafile=certifi.where())
    if CA_BUNDLE.exists():
        ctx.load_verify_locations(cafile=str(CA_BUNDLE))
    return ctx


# Реестры, недоступные из сети сервера (Роспатент висит 50 с, SEC отвечает 403 на часть адресов): после сбоя хост
# пропускается во всех запросах на DOWN_COOLDOWN секунд, чтобы каждый прогон не ждал его заново.
DOWN_HOSTS = {"searchplatform.rospatent.gov.ru", "efts.sec.gov", "zakupki.gov.ru", "api.lens.org", "cyberleninka.ru"}
DOWN_COOLDOWN = 1800.0
_DOWN: dict[str, float] = {}


def host_down(host: str) -> bool:
    return _DOWN.get(host, 0.0) > time.monotonic()


USER_AGENT = "weak-signals-lct2026/0.1 (research prototype; +https://github.com/Krackenhell/lct-2026-weak-signals)"

# Минимальный интервал между запросами к хосту (секунды) — по правилам API источников.
HOST_INTERVAL = {
    "export.arxiv.org": 3.1,
    "api.gdeltproject.org": 5.5,
    "api.github.com": 2.2,
    "api.openalex.org": 0.15,
    "hn.algolia.com": 0.2,
    "api.crossref.org": 0.34,  # вежливый пул Crossref — около 3 запросов в секунду
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
    "api.search.brave.com": 1.1,
    "eutils.ncbi.nlm.nih.gov": 0.12,  # с ключом — до 10 запросов в секунду
    "api.adsabs.harvard.edu": 0.3,
    "api.biorxiv.org": 0.3,
    "api.stackexchange.com": 0.15,
    "clinicaltrials.gov": 0.3,
    "efts.sec.gov": 0.15,
    "ops.epo.org": 1.0,  # частый поиск EPO блокирует как «робота» (403 CLIENT.RobotDetected)  # SEC — не больше 10 запросов в секунду
    "searchplatform.rospatent.gov.ru": 0.5,
    "zakupki.gov.ru": 1.5,  # бесплатный тариф Brave — 1 запрос в секунду
}


# Время жизни кэша по хостам (часы), если оно больше общего CACHE_TTL_HOURS. Ряды публикаций OpenAlex за прошлые годы
# не меняются, а квота ключа — около 13 холодных запросов в сутки: 10 суток кэша экономят её на повторных темах.
HOST_TTL_HOURS = {"api.openalex.org": 240, "api.search.brave.com": 240}  # Brave — 2000 запросов в месяц, кэш бережёт квоту

# Сетевые запросы к OpenAlex за текущие сутки (UTC) — сохраняются в data/openalex_usage.json, чтобы предрасчёт
# не съедал квоту живых запросов (см. OPENALEX_DAILY_SOFT_LIMIT).
_OA_USAGE: dict[str, int] = {}


def _usage_path() -> Path:
    return Path(get_settings().cache_dir).parent / "openalex_usage.json"


def openalex_calls_today() -> int:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    if day not in _OA_USAGE:
        try:
            _OA_USAGE.clear()
            _OA_USAGE.update({k: int(v) for k, v in json.loads(_usage_path().read_text(encoding="utf-8")).items() if k == day})
        except (OSError, ValueError):
            pass
        _OA_USAGE.setdefault(day, 0)
    return _OA_USAGE[day]


def _count_openalex() -> None:
    day = time.strftime("%Y-%m-%d", time.gmtime())
    _OA_USAGE[day] = openalex_calls_today() + 1
    if _OA_USAGE[day] % 10 == 0:  # не пишем файл на каждый запрос
        try:
            _usage_path().write_text(json.dumps({day: _OA_USAGE[day]}), encoding="utf-8")
        except OSError:
            pass


# Таймаут запроса по хостам (секунды), если он короче общего HTTP_TIMEOUT: реестры, которые из части сетей не отвечают
# вовсе (Роспатент держит соединение 50 с), должны отвалиться раньше лимита рыночного слоя и попасть в DOWN_HOSTS.
HOST_TIMEOUT = {"cyberleninka.ru": 12.0, "searchplatform.rospatent.gov.ru": 10.0, "efts.sec.gov": 10.0, "zakupki.gov.ru": 12.0, "api.lens.org": 15.0}

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


def _write_cache(path: Path, data: Any) -> None:
    """Запись через временный файл: параллельный запуск не прочитает файл, записанный наполовину."""
    tmp = path.with_suffix(f".{os.getpid()}.{id(data)}.tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:  # нет места на диске — работаем без кэша, а не падаем
        log.warning("cache write failed %s: %s", path.name, exc)
        tmp.unlink(missing_ok=True)


def prune_cache(cache_dir: Path, ttl_hours: int) -> int:
    """Удаляет просроченные файлы кэша (при запуске сервера), чтобы кэш не рос без предела.
    По имени файла хост не определить (это хэш), поэтому срок — наибольший из общего и по хостам."""
    if not cache_dir.exists():
        return 0
    ttl_hours = max([ttl_hours, *HOST_TTL_HOURS.values()]) if ttl_hours else ttl_hours
    limit, n = time.time() - ttl_hours * 3600, 0
    for f in cache_dir.iterdir():
        try:
            if f.suffix in (".json", ".tmp") and f.stat().st_mtime < limit:
                f.unlink()
                n += 1
        except OSError:
            continue
    return n


def proxy_routes() -> dict[str, str]:
    """Хост → прокси по настройкам RU_PROXY_* и FOREIGN_PROXY_* (пустой прокси — маршрута нет)."""
    s = get_settings()
    routes = {}
    for url, hosts in ((s.foreign_proxy_url, s.foreign_proxy_hosts), (s.ru_proxy_url, s.ru_proxy_hosts)):
        if url:
            routes.update({h.strip().lower(): url for h in (hosts or "").split(",") if h.strip()})
    return routes


def _mounts(timeout: float) -> dict:
    routes = proxy_routes()
    return {f"all://{host}": httpx.AsyncHTTPTransport(proxy=url, verify=_ctx(), retries=0) for host, url in routes.items()}


# Сколько раз прокси не ответил: после 3 подряд хост на PROXY_COOLDOWN секунд ходит напрямую (прокси упал — работаем как без него).
_PROXY_FAILS: dict[str, int] = {}
_PROXY_OFF_UNTIL: dict[str, float] = {}
PROXY_COOLDOWN = 600.0


_CTX: list[ssl.SSLContext] = []


def _ctx() -> ssl.SSLContext:
    if not _CTX:
        _CTX.append(ssl_context())
    return _CTX[0]


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
            timeout=s.http_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True, verify=_ctx(), mounts=_mounts(s.http_timeout)
        )
        # Прямой клиент — запасной путь, если прокси для хоста недоступен.
        self._direct = httpx.AsyncClient(timeout=s.http_timeout, headers={"User-Agent": USER_AGENT}, follow_redirects=True, verify=_ctx())             if proxy_routes() else self._client
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
        if self._direct is not self._client:
            await self._direct.aclose()

    async def _send(self, host: str, method: str, url: str, **kw) -> httpx.Response:
        """Запрос по маршруту хоста (через прокси, если он задан) с переходом на прямое соединение при сбое прокси."""
        routed = self._direct is not self._client and host in proxy_routes()
        proxied = routed and _PROXY_OFF_UNTIL.get(host, 0.0) < time.monotonic()
        # Хосты без маршрута и так идут напрямую через основной клиент; прямой клиент — только когда прокси хоста выключен.
        client = self._direct if routed and not proxied else self._client
        try:
            resp = await client.request(method, url, **kw)
        except (httpx.ProxyError, httpx.ConnectError, httpx.ConnectTimeout) as exc:
            if not proxied:
                raise
            _PROXY_FAILS[host] = _PROXY_FAILS.get(host, 0) + 1
            if _PROXY_FAILS[host] >= 3:
                _PROXY_OFF_UNTIL[host] = time.monotonic() + PROXY_COOLDOWN
            log.warning("proxy for %s failed (%s), retrying direct", host, type(exc).__name__)
            return await self._direct.request(method, url, **kw)
        if proxied:
            _PROXY_FAILS[host] = 0
        return resp

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
        ttl = max(self._ttl, HOST_TTL_HOURS.get(host, 0) * 3600) if self._ttl else 0  # CACHE_TTL_HOURS=0 — кэш выключен везде
        if cache and path.exists() and time.time() - path.stat().st_mtime < ttl:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self._bump(host, "cached")
                return data
            except (OSError, ValueError):  # повреждённый файл кэша (сбой питания, диск заполнен) — читаем из источника
                path.unlink(missing_ok=True)

        if host in DOWN_HOSTS and host_down(host) and not self.patient:
            self._bump(host, "failed")
            raise SourceError(f"{host} недоступен из сети сервера (повтор через {DOWN_COOLDOWN / 60:.0f} мин)")
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
            if host == "api.openalex.org":
                _count_openalex()
            backoff = 1.5 * (attempt + 1) + self._interval.get(host, 0)
            try:
                tmo = {"timeout": HOST_TIMEOUT[host]} if host in HOST_TIMEOUT and not self.patient else {}
                if json_body is None:
                    resp = await self._send(host, "GET", url, params=params, headers=headers, **tmo)
                else:
                    resp = await self._send(host, "POST", url, params=params, headers=headers, json=json_body, **tmo)
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
                if resp.status_code == 403 and host in DOWN_HOSTS:
                    _DOWN[host] = time.monotonic() + DOWN_COOLDOWN  # доступ закрыт для адреса сервера — не повторяем
                if resp.status_code >= 400:
                    # Ошибка запроса (например, 404): источник исправен, повторять бессмысленно. 404 у EPO и ряда API —
                    # обычный ответ «ничего не найдено», в статистике это не сбой.
                    self._bump(host, "ok" if resp.status_code == 404 else "failed")
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
                    _write_cache(path, data)
                self._bump(host, "ok")
                self._fails[host] = 0
                return data
            except NotFound:
                raise
            except (httpx.HTTPError, SourceError) as exc:
                last_exc = exc if str(exc) else SourceError(type(exc).__name__)  # у таймаутов httpx текст пустой
                if host in DOWN_HOSTS and isinstance(exc, (httpx.TimeoutException, httpx.RemoteProtocolError, httpx.ConnectError)):
                    _DOWN[host] = time.monotonic() + DOWN_COOLDOWN
                    break
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
