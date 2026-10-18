"""Проверка ссылок источников: каждая ссылка в итоговой выдаче открывается вживую.

Итог по ссылке:
  ok          — страница открылась (код ответа < 400);
  dead        — страницы нет (404, 410) или домен не отвечает — такой источник не показывается как подтверждение;
  restricted  — сайт ограничивает автоматическую проверку (401, 403, 405, 429) — ссылку проверить нельзя, но она не считается битой.
"""
import asyncio
import ipaddress
import logging
from urllib.parse import urlparse

import httpx

from app.collectors.http import USER_AGENT

log = logging.getLogger(__name__)
DEAD = {404, 410}
RESTRICTED = {401, 403, 405, 406, 429, 451}


def _internal(url: str) -> bool:
    """Адрес внутренней сети: такие ссылки из чужих лент сервер банка не открывает (защита от обращений к внутренним сервисам)."""
    host = (urlparse(url).hostname or "").lower()
    if host in ("localhost", "") or host.endswith((".local", ".internal", ".localhost")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified


class _Internal(Exception):
    pass


async def _guard(request: httpx.Request) -> None:
    """Каждый запрос, включая переадресации, проверяется на внутренний адрес."""
    if _internal(str(request.url)):
        raise _Internal(str(request.url))


async def check_one(client: httpx.AsyncClient, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "dead"
    if _internal(url):
        return "restricted"
    try:
        r = await client.head(url)
        if r.status_code in (405, 501) or r.status_code >= 500:
            r = await client.get(url, headers={"Range": "bytes=0-1023"})  # часть сайтов не поддерживает HEAD
    except _Internal:
        return "restricted"  # переадресация во внутреннюю сеть
    except (httpx.ConnectError, httpx.UnsupportedProtocol, httpx.InvalidURL):
        return "dead"
    except httpx.HTTPError:
        return "restricted"  # таймаут или сбой сети: не утверждаем, что ссылка битая
    if r.status_code < 400:
        return "ok"
    if r.status_code in DEAD:
        return "dead"
    return "restricted" if r.status_code in RESTRICTED else "dead" if r.status_code < 500 else "restricted"


async def check_all(urls: list[str], concurrency: int = 10, timeout: float = 8.0, transport: httpx.AsyncBaseTransport | None = None) -> dict[str, str]:
    urls = list(dict.fromkeys(u for u in urls if u))
    sem = asyncio.Semaphore(concurrency)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}, transport=transport,
                                 event_hooks={"request": [_guard]}) as client:

        async def one(u):
            async with sem:
                return u, await check_one(client, u)

        return dict(await asyncio.gather(*(one(u) for u in urls)))
