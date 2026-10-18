"""Патенты через EPO Open Patent Services (OPS) — официальный API Европейского патентного ведомства.

В базе DOCDB есть публикации более 100 ведомств, включая Китай (CN), США, Японию, Корею и Россию. По технологии
считаем число патентных публикаций за 3 года и долю китайских — Китай подаёт больше всех патентов в мире,
и рост китайских заявок часто опережает статьи и продукты.

Нужен бесплатный ключ: регистрация на https://developers.epo.org (приложение → Consumer Key и Consumer Secret),
значения — в .env: EPO_OPS_KEY и EPO_OPS_SECRET. Без ключа источник выключен и ни одного запроса не делает.
Google Patents не используется: его robots.txt запрещает автоматический доступ.
"""
import base64
import time
from datetime import date

from app.collectors.base import RawDoc
from app.collectors.http import HttpClient, NotFound, SourceError
from app.config import get_settings

TOKEN_URL = "https://ops.epo.org/3.2/auth/accesstoken"
SEARCH = "https://ops.epo.org/3.2/rest-services/published-data/search"
_TOKEN: dict = {}


def enabled() -> bool:
    s = get_settings()
    return bool(s.epo_ops_key and s.epo_ops_secret)


async def _token(http: HttpClient) -> str:
    if _TOKEN.get("value") and _TOKEN.get("until", 0) > time.time() + 60:
        return _TOKEN["value"]
    s = get_settings()
    basic = base64.b64encode(f"{s.epo_ops_key}:{s.epo_ops_secret}".encode()).decode()
    resp = await http._client.post(TOKEN_URL, data={"grant_type": "client_credentials"}, headers={"Authorization": f"Basic {basic}"})
    if resp.status_code != 200:
        raise SourceError(f"EPO OPS token: HTTP {resp.status_code}")
    data = resp.json()
    _TOKEN.update(value=data["access_token"], until=time.time() + int(data.get("expires_in", 1200)))
    return _TOKEN["value"]


def _cql(phrase: str, from_year: int, country: str | None = None) -> str:
    q = f'ta="{phrase.replace(chr(34), "")}" and pd>={from_year}'  # ta — название или реферат
    return q + (f" and pn={country}" if country else "")


def _refs(data: dict) -> tuple[int, list[dict]]:
    bs = ((data.get("ops:world-patent-data") or {}).get("ops:biblio-search") or {})
    total = int(bs.get("@total-result-count") or 0)
    refs = ((bs.get("ops:search-result") or {}).get("ops:publication-reference")) or []
    return total, refs if isinstance(refs, list) else [refs]


async def _search(http: HttpClient, cql: str, rng: str = "1-1") -> dict:
    token = await _token(http)
    try:
        return await http.get(SEARCH, params={"q": cql, "Range": rng}, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    except NotFound:  # OPS отвечает 404, когда по запросу ничего нет
        return {}


async def patent_counts(http: HttpClient, phrase: str, years: int = 3) -> dict | None:
    """Патентные публикации за years лет: всего и из Китая. None — ключа нет."""
    if not enabled():
        return None
    since = date.today().year - years + 1
    total, _ = _refs(await _search(http, _cql(phrase, since)))
    cn, _ = _refs(await _search(http, _cql(phrase, since, "CN"))) if total else (0, [])
    return {"since": since, "total": total, "china": cn, "china_share": round(cn / total, 3) if total else None}


async def search(http: HttpClient, phrase: str, n: int = 5, years: int = 3) -> list[RawDoc]:
    if not enabled():
        return []
    _, refs = _refs(await _search(http, _cql(phrase, date.today().year - years + 1), f"1-{n}"))
    docs = []
    for r in refs:
        d = (r.get("document-id") or {}) if isinstance(r, dict) else {}
        country = (d.get("country") or {}).get("$", "")
        number = (d.get("doc-number") or {}).get("$", "")
        kind = (d.get("kind") or {}).get("$", "")
        if not (country and number):
            continue
        docs.append(RawDoc(
            url=f"https://worldwide.espacenet.com/patent/search?q=pn%3D{country}{number}{kind}",
            title=f"Патентная публикация {country}{number}{kind} по теме «{phrase}»",
            snippet="Найдено в EPO OPS (название или реферат).", published=None,
            source_name=f"EPO OPS ({country})", source_type="patent", language="en", collector="epo", extra={"country": country},
        ))
    return docs
