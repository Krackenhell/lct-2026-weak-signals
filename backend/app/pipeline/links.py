"""Проверка ссылок источников: каждая ссылка в итоговой выдаче открывается вживую.

Итог по ссылке:
  ok          — страница открылась (код ответа < 400);
  dead        — страницы нет (404, 410) или домен не отвечает — такой источник не показывается как подтверждение;
  restricted  — сайт ограничивает автоматическую проверку (401, 403, 405, 429) — ссылку проверить нельзя, но она не считается битой.
"""
import asyncio
import logging

import httpx

from app.collectors.http import USER_AGENT

log = logging.getLogger(__name__)
DEAD = {404, 410}
RESTRICTED = {401, 403, 405, 406, 429, 451}


async def check_one(client: httpx.AsyncClient, url: str) -> str:
    if not url.startswith(("http://", "https://")):
        return "dead"
    try:
        r = await client.head(url)
        if r.status_code in (405, 501) or r.status_code >= 500:
            r = await client.get(url, headers={"Range": "bytes=0-1023"})  # часть сайтов не поддерживает HEAD
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
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": USER_AGENT}, transport=transport) as client:

        async def one(u):
            async with sem:
                return u, await check_one(client, u)

        return dict(await asyncio.gather(*(one(u) for u in urls)))
