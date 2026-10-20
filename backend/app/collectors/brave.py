"""Brave Search API — открытый веб-поиск по официальному API (без парсинга выдачи поисковиков).

Зачем: научные базы почти не видят отраслевых событий — пилотов, контрактов, сделок, закупок, — а ленты изданий
покрывают в основном ИТ и финтех. Поиск по вебу и новостям закрывает «рыночные» ступени лестницы и находит доводы «против».

Ограничения бесплатного тарифа: 1 запрос в секунду и 2000 в месяц. Поэтому:
- пауза 1,1 с между запросами (общая для процесса), кэш ответов 10 суток;
- бюджет запросов на один прогон (BRAVE_MAX_CALLS_PER_RUN) и месячный счётчик (BRAVE_MONTHLY_LIMIT) — при исчерпании
  источник просто не используется, прогон идёт дальше;
- результаты в числовые признаки классификатора не входят: только документы-доказательства, лестница и доводы «против».
"""
import json
import re
import time
from pathlib import Path

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient, SourceError
from app.collectors.news_search import event_of
from app.config import get_settings

WEB = "https://api.search.brave.com/res/v1/web/search"
NEWS = "https://api.search.brave.com/res/v1/news/search"
HOST = "api.search.brave.com"


def enabled() -> bool:
    return bool(get_settings().brave_api_key)


# ---------------------------------------------------------------- учёт запросов

_MONTH: dict[str, int] = {}


def _usage_path() -> Path:
    return Path(get_settings().cache_dir).parent / "brave_usage.json"


def calls_this_month() -> int:
    month = time.strftime("%Y-%m", time.gmtime())
    if month not in _MONTH:
        _MONTH.clear()
        try:
            _MONTH.update({k: int(v) for k, v in json.loads(_usage_path().read_text(encoding="utf-8")).items() if k == month})
        except (OSError, ValueError):
            pass
        _MONTH.setdefault(month, 0)
    return _MONTH[month]


def _count() -> None:
    month = time.strftime("%Y-%m", time.gmtime())
    _MONTH[month] = calls_this_month() + 1
    try:
        _usage_path().write_text(json.dumps({month: _MONTH[month]}), encoding="utf-8")
    except OSError:
        pass


class Budget:
    """Сколько запросов к Brave может сделать один прогон. Кэшированные ответы бюджет не тратят."""

    def __init__(self, limit: int | None = None):
        s = get_settings()
        self.limit = s.brave_max_calls_per_run if limit is None else limit
        self.used = 0

    def take(self) -> bool:
        s = get_settings()
        if not enabled() or self.used >= self.limit or calls_this_month() >= s.brave_monthly_limit:
            return False
        self.used += 1
        return True


# ---------------------------------------------------------------- поиск

# Тип рыночного события по заголовку и фрагменту — для ступеней лестницы. Порядок важен: раунд и контракт раньше пилота.
MARKET = [
    ("funding", re.compile(r"\braise[sd]?\b|funding round|series [a-e]\b|seed round|\binvest(s|ed|ment)\b|acquir|раунд|инвестиц|привлек", re.I)),
    ("contract", re.compile(r"\bcontract\b|\bawarded\b|\btender\b|purchase order|закупк|контракт|тендер|госзаказ", re.I)),
    ("pilot", re.compile(r"\bpilot\b|field trial|demonstration plant|пилот|опытн\w+ эксплуатац|испытани", re.I)),
    ("launch", re.compile(r"\blaunch(es|ed)?\b|commerciali[sz]|series production|mass production|\bunveil|запуск|серийн", re.I)),
]


def market_event(text: str) -> str | None:
    return next((k for k, rx in MARKET if rx.search(text or "")), None)


def _date(it: dict) -> str | None:
    d = it.get("page_age") or ""
    return d[:10] if re.match(r"\d{4}-\d{2}-\d{2}", d) else None


def _domain(url: str) -> str:
    m = re.match(r"https?://(?:www\.)?([^/]+)", url or "")
    return m.group(1).lower() if m else ""


async def _get(http: HttpClient, url: str, q: str, count: int, freshness: str | None, budget: Budget | None) -> list[dict]:
    params = {"q": q, "count": count, "safesearch": "moderate"}
    if freshness:
        params["freshness"] = freshness
    path = http._cache_path(url, params)
    cached = path.exists()  # ответ из кэша не тратит ни бюджет прогона, ни месячную квоту
    if not cached and budget is not None and not budget.take():
        raise SourceError("Brave: бюджет запросов исчерпан")
    data = await http.get(url, params=params, headers={"X-Subscription-Token": get_settings().brave_api_key, "Accept": "application/json"})
    if not cached:
        _count()
    return (data.get("web") or {}).get("results") or data.get("results") or []


async def search(http: HttpClient, q: str, count: int = 10, news: bool = False, freshness: str | None = "py2",
                 budget: Budget | None = None) -> list[RawDoc]:
    """Веб- или новостной поиск. freshness: pd/pw/pm/py — день/неделя/месяц/год; py2 — два года (свой формат: дата от)."""
    fr = None
    if freshness == "py2":
        y = time.gmtime().tm_year
        fr = f"{y - 2}-{time.strftime('%m-%d', time.gmtime())}to{time.strftime('%Y-%m-%d', time.gmtime())}"
    elif freshness:
        fr = freshness
    items = await _get(http, NEWS if news else WEB, q, count, fr, budget)
    docs = []
    for it in items:
        url, title = it.get("url") or "", clean(it.get("title"), 400)
        if not url or not title:
            continue
        snippet = clean(re.sub(r"<[^>]+>", " ", " ".join([it.get("description") or "", *(it.get("extra_snippets") or [])])), 800)
        dom = _domain(url)
        docs.append(RawDoc(
            url=url, title=title, snippet=snippet, published=_date(it), source_name=f"{dom} (Brave Search)",
            source_type="news", language=(it.get("language") or "en")[:2], collector="brave",
            # event — в общей шкале паспорта (funding / launch), market — точный тип для лестницы.
            extra={"event": event_of(f"{title}. {snippet}") or {"funding": "funding", "contract": "launch", "pilot": "launch",
                                                                   "launch": "launch"}.get(market_event(f"{title}. {snippet}") or ""),
                   "market": market_event(f"{title}. {snippet}"), "publisher_domain": dom},
        ))
    return docs


# ---------------------------------------------------------------- ступени лестницы и доводы «против»

# Короткий запрос веб-поиска (длинные OR-цепочки и новостной поиск Brave находили меньше, проверено 20.10)
EVENT_Q = '"{p}" pilot OR contract OR funding OR deployment'
PATENT_Q = 'site:patents.google.com "{p}"'
PROCUREMENT_Q = 'site:zakupki.gov.ru "{p}"'
AGAINST_Q = '"{p}" discontinued OR abandoned OR failed OR "widely adopted" OR "industry standard"'
AGAINST = re.compile(r"discontinu|abandon|failed to|failure of|shut(s|ting)? down|bankrupt|recall|widely adopted|mature technology|"
                     r"industry standard|mainstream|commodit|прекращ|закрыт|банкрот|отказал|устаревш|массово|стандарт отрасли", re.I)


def _mentions(docs: list[RawDoc], phrase: str) -> list[RawDoc]:
    words = [w for w in re.findall(r"[a-zа-яё0-9]{3,}", phrase.lower())]
    return [d for d in docs if words and all(w in f"{d.title} {d.snippet}".lower() for w in words)]


async def patents(http: HttpClient, phrase: str, budget: Budget) -> list[RawDoc]:
    """Патенты с точной фразой (Google Patents через веб-поиск): ступень «патент»."""
    docs = _mentions(await search(http, PATENT_Q.format(p=phrase), 10, freshness=None, budget=budget), phrase)
    for d in docs:
        d.source_type, d.extra = "patent", {**d.extra, "event": "patent"}
    return docs


async def procurement(http: HttpClient, phrase_ru: str, budget: Budget) -> list[RawDoc]:
    """Российские госзакупки с русским названием технологии: ступень «закупка»."""
    docs = _mentions(await search(http, PROCUREMENT_Q.format(p=phrase_ru), 10, freshness=None, budget=budget), phrase_ru)
    for d in docs:
        d.source_type, d.extra = "regulator", {**d.extra, "event": "procurement"}
    return docs


async def events(http: HttpClient, phrase: str, budget: Budget, n: int = 10) -> list[RawDoc]:
    """Пилоты, контракты, раунды, запуски за 2 года: событийные ступени лестницы."""
    return [d for d in _mentions(await search(http, EVENT_Q.format(p=phrase), n, budget=budget), phrase) if d.extra.get("event")]


async def against(http: HttpClient, phrase: str, budget: Budget, n: int = 10) -> list[RawDoc]:
    """Доводы «против»: признаки провала, отказа или, наоборот, массовости (тогда это уже не ранний сигнал)."""
    docs = _mentions(await search(http, AGAINST_Q.format(p=phrase), n, freshness=None, budget=budget), phrase)
    return [d for d in docs if AGAINST.search(f"{d.title} {d.snippet}")]
