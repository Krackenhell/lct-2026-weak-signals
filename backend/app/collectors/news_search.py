"""Отраслевые новости: прямые RSS-ленты изданий и поиск SiliconANGLE.

Зачем: 87% ссылок в 100 сигналах организатора — сайты компаний, стартап-издания и СМИ, а в обоснованиях
слова «раунд / seed / Series A/B» встречаются 112 раз. Научные индексы такие события не видят.

Читаем только то, что издания разрешают роботам (robots.txt проверяется перед каждой лентой, см. robots.py).
Поэтому здесь нет поиска Google News (robots.txt закрывает /rss/search) и поиска TechCrunch (закрыт /?s=):
вместо поиска берём ленты разделов и отбираем записи по словам запроса. Finextra оставлена в списке
намеренно: её /rss/ закрыт, проверка это видит и ленту не запрашивает (в статистике — robots_blocked).
SiliconANGLE (WordPress) разрешает всё, включая RSS поиска по архиву.
"""
import asyncio
import re
import time
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlparse

import feedparser

from app.collectors import robots
from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient, SourceError

SILICONANGLE = "https://siliconangle.com/?s={q}&feed=rss2"

FIN = r"финтех|fintech|финанс|financ|банк|bank|платеж|payment|крипт|crypto|стейбл|stablecoin|токениз|tokeniz"
SEC = r"безопасн|security|кибер|cyber|защит"
ROB = r"робот|robot"
AI = r"\bии\b|\bai\b|искусственн|нейросет|машинн|machine learning|edge|вычислен|comput|индустр|industr"

# (адрес ленты, издание, язык, тема). Ленты разделов, а не главные страницы: в них меньше шума.
# Если запрос относится к теме ленты, в корпус идут все её свежие записи; иначе — только совпавшие по словам.
FEEDS: list[tuple[str, str, str, str | None]] = [
    ("https://techcrunch.com/category/fintech/feed/", "TechCrunch", "en", FIN),
    ("https://techcrunch.com/category/artificial-intelligence/feed/", "TechCrunch", "en", AI),
    ("https://techcrunch.com/category/robotics/feed/", "TechCrunch", "en", ROB),
    ("https://techcrunch.com/category/security/feed/", "TechCrunch", "en", SEC),
    ("https://techcrunch.com/category/venture/feed/", "TechCrunch", "en", None),
    ("https://techcrunch.com/tag/funding/feed/", "TechCrunch", "en", None),
    ("https://www.theblock.co/rss.xml", "The Block", "en", FIN),
    ("https://www.prnewswire.com/rss/news-releases-list.rss", "PR Newswire", "en", None),
    ("https://www.prnewswire.com/rss/financial-services-latest-news/financial-services-latest-news-list.rss", "PR Newswire", "en", FIN),
    ("https://www.prnewswire.com/rss/consumer-technology-latest-news/consumer-technology-latest-news-list.rss", "PR Newswire", "en", None),
    ("https://siliconangle.com/feed/", "SiliconANGLE", "en", AI),
    ("https://www.finextra.com/rss/headlines.aspx", "Finextra", "en", FIN),
    ("https://vc.ru/rss", "vc.ru", "ru", None),
    ("https://www.cnews.ru/inc/rss/news.xml", "CNews", "ru", None),
    # Китай — крупнейший рынок ранних внедрений: англоязычные издания о китайских технологиях…
    ("https://technode.com/feed/", "TechNode", "en", None),
    ("https://pandaily.com/feed/", "Pandaily", "en", None),
    ("https://www.scmp.com/rss/36/feed", "SCMP Tech", "en", None),
    # …и китайские техно-СМИ (отбор по китайским фразам из плана запроса)
    ("https://www.36kr.com/feed-article", "36Kr", "zh", None),
    ("https://www.ithome.com/rss/", "IT之家", "zh", None),
    ("https://www.cnbeta.com.tw/backend.php", "cnBeta", "zh", None),
    ("https://www.infoq.cn/feed", "InfoQ China", "zh", None),
]
# Ленты тегов WordPress (/tag/<тег>/feed/) разрешены robots.txt, в отличие от поиска TechCrunch (/?s=),
# и уходят на годы назад: по тегу «stablecoins» — до 2022 года. Нет такого тега — сайт отвечает ошибкой, это не сбой.
TAG_FEEDS = [("https://techcrunch.com/tag/{slug}/feed/", "TechCrunch"), ("https://siliconangle.com/tag/{slug}/feed/", "SiliconANGLE")]

# События финансирования и выхода на рынок: самое «твёрдое» свидетельство для слабого сигнала по версии датасета.
FUNDING = re.compile(
    r"\braise[sd]?\b|\braising\b|\bseries [a-e]\b|\bseed (round|funding)\b|\bpre-seed\b|\bfunding round\b|\bsecures? \$|"
    r"\b\$\d[\d.,]*\s?(m|mn|million|b|bn|billion)\b|\bbacked by\b|\bacquires?\b|\bacquisition\b|"
    r"привлек\w*|раунд|инвестиц\w*|посевн\w*|сделк\w*|поглощ\w*|приобрет\w*|"
    r"融资|[A-E天种]轮|收购|获投|投资",
    re.I,
)
LAUNCH = re.compile(r"\blaunch(es|ed)?\b|\bunveil(s|ed)?\b|\brolls? out\b|\bpilot\b|запуска\w*|запусти\w*|представил\w*|пилот\w*|"
                    r"发布|推出|上线|试点|量产", re.I)

# Слова, которые есть почти в любой новости о технологиях: по ним запись к теме не относим.
COMMON = {
    "the", "and", "for", "with", "new", "using", "based", "system", "systems", "technology", "technologies", "data",
    "model", "models", "platform", "solution", "solutions", "startup", "startups", "company", "companies", "service",
    "services", "market", "digital", "smart", "intelligence", "artificial", "learning", "machine", "funding", "raises",
    "для", "и", "в", "на", "с", "по", "технологии", "технология", "решения", "система", "системы", "данные", "компания",
    "рынок", "сервис", "цифровой", "цифровые", "искусственный", "интеллект",
}


# Слова, которые LLM приставляет к любой теме: «machine learning in gaslift control» приводил в корпус запроса о газлифте
# все новости про ИИ. Игнорируются, только если их нет в самом запросе: для «квантовых сенсоров» «quantum» — главное слово.
GENERIC_EXTRA = {"quantum", "computing", "autonomous", "optimization", "control", "monitoring", "management", "neural", "deep",
                 "agent", "agents", "agentic", "modeling", "modelling", "analytics", "efficiency", "advanced", "generation", "innovative"}


def generic_for(topic_text: str) -> set[str]:
    """Основы общих слов, которые нужно игнорировать для этого запроса (те, что в нём не встречаются)."""
    asked = _stems(topic_text)
    return {w[:5] for w in GENERIC_EXTRA} - asked


def event_of(text: str) -> str | None:
    """Тип события в заголовке новости: раунд или сделка, запуск или пилот, иначе None."""
    if FUNDING.search(text or ""):
        return "funding"
    if LAUNCH.search(text or ""):
        return "launch"
    return None


def _date(s: str | None) -> str | None:
    try:
        return parsedate_to_datetime(s).date().isoformat() if s else None
    except (TypeError, ValueError):
        return None


def _domain(url: str) -> str:
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _stems(text: str) -> set[str]:
    """Основы слов: первые 5 букв, чтобы «платежи» и «платежей», «payment» и «payments» совпадали."""
    words = re.findall(r"[a-zа-яё0-9][a-zа-яё0-9\-]{2,}", (text or "").lower())
    return {w[:5] for w in words if w not in COMMON}


CJK = re.compile(r"[一-鿿]")


def _bigrams(text: str) -> set[str]:
    chars = "".join(CJK.findall(text or ""))
    return {chars[i : i + 2] for i in range(len(chars) - 1)} if len(chars) > 1 else set(chars)


def _blocked(http: HttpClient, url: str) -> None:
    host = urlparse(url).netloc
    st = http.stats.setdefault(host, {"ok": 0, "cached": 0, "failed": 0})
    st["robots_blocked"] = st.get("robots_blocked", 0) + 1


# Разобранные ленты в памяти процесса. Скорость: лента TechNode — 11 МБ и 2000 записей; раньше её заново разбирал
# каждый из 30 кандидатов, и синхронный разбор на минуту блокировал все остальные запросы (замер 19.10).
FEED_TTL = 1800.0
_PARSED: dict[str, tuple[float, list[RawDoc]]] = {}


async def _feed(http: HttpClient, url: str, publisher: str, lang: str) -> list[RawDoc]:
    hit = _PARSED.get(url)
    if hit and time.monotonic() - hit[0] < FEED_TTL:
        return hit[1]
    if not await robots.allowed(http, url):
        _blocked(http, url)
        return []
    try:
        text = await http.get(url, as_json=False)
    except SourceError:
        return []
    docs = await asyncio.to_thread(_parse_feed, text, url, publisher, lang)  # разбор — в отдельном потоке
    _PARSED[url] = (time.monotonic(), docs)
    return docs


def _parse_feed(text: str, url: str, publisher: str, lang: str) -> list[RawDoc]:
    docs = []
    for e in feedparser.parse(text).entries:
        title = clean(e.get("title"), 400)
        link = re.sub(r"\?utm_.*$", "", e.get("link", ""))
        if not title or not link:
            continue
        snippet = clean(re.sub(r"<[^>]+>", " ", e.get("summary", "")), 800)
        docs.append(
            RawDoc(
                url=link,
                title=title,
                snippet=snippet,
                published=_date(e.get("published")),
                source_name=publisher,
                source_type="news",
                language=lang,
                collector="rss",
                extra={"publisher_domain": _domain(link) or _domain(url), "event": event_of(f"{title} {snippet}"), "via": "RSS"},
            )
        )
    return docs


def _unique(docs) -> list[RawDoc]:
    seen, out = set(), []
    for d in docs:
        if d.url not in seen:
            seen.add(d.url)
            out.append(d)
    return out


async def industry_feeds(http: HttpClient, lang: str = "en", topic: str | None = None) -> list[RawDoc]:
    """Разрешённые ленты на языке lang. topic задан — только ленты, тема которых совпала с ним.
    Ответы кэшируются, поэтому повторные вызовы в запуске бесплатны."""
    feeds = [f for f in FEEDS if f[2] == lang and (topic is None or (f[3] and re.search(f[3], topic, flags=re.I)))]
    batches = await asyncio.gather(*(_feed(http, u, p, lg) for u, p, lg, _ in feeds))
    return _unique(d for b in batches for d in b)


def slug(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", term.lower()).strip("-")


async def tag_feeds(http: HttpClient, terms: list[str], n: int = 20) -> list[RawDoc]:
    """Записи лент тегов по подтемам: публикации, которые сами редакции отнесли к теме."""
    jobs = [_feed(http, tpl.format(slug=slug(t)), pub, "en") for t in terms if re.fullmatch(r"[\x00-\x7f]+", t) and slug(t)
            for tpl, pub in TAG_FEEDS]
    batches = await asyncio.gather(*jobs)
    return _unique(d for b in batches for d in b[:n])


def select(docs: list[RawDoc], terms: list[str], n: int = 20, min_score: int = 2, ignore: set[str] | frozenset = frozenset()) -> list[RawDoc]:
    """Записи лент, относящиеся к теме: у одного из терминов совпало не меньше min_score основ слов
    (у однословного термина — само слово). Выше — больше совпадений, затем новости о раундах и запусках.
    ignore — основы общих слов, которые для этого запроса не считаются (см. generic_for)."""
    term_stems = [s for s in (_stems(t) - ignore for t in terms if t and not CJK.search(t)) if s]
    # В китайском нет пробелов: сравниваем пары соседних иероглифов, нужно совпадение 60% пар термина.
    term_bigrams = [b for b in (_bigrams(t) for t in terms if t and CJK.search(t)) if b]
    scored = []
    for d in docs:
        text = _stems(f"{d.title} {d.snippet}")
        hits = [len(ts & text) for ts in term_stems if len(ts & text) >= min(min_score, len(ts))]
        if term_bigrams:
            zh = _bigrams(f"{d.title} {d.snippet}")
            hits += [len(tb & zh) for tb in term_bigrams if len(tb & zh) >= max(1, round(0.6 * len(tb)))]
        if hits:
            scored.append((max(hits), bool(d.extra.get("event")), d.published or "", d))
    scored.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    return [d for *_, d in scored[:n]]


async def matching(http: HttpClient, terms: list[str], lang: str = "en", n: int = 20, min_score: int = 2,
                   ignore: set[str] | frozenset = frozenset()) -> list[RawDoc]:
    return select(await industry_feeds(http, lang), terms, n, min_score, ignore)


async def for_topic(http: HttpClient, topic_text: str, terms: list[str], lang: str = "en", n: int = 80) -> list[RawDoc]:
    """Корпус новостей для запроса: все записи тематических лент + совпавшие по словам из остальных
    + ленты тегов по подтемам (только для английского)."""
    themed = await industry_feeds(http, lang, topic_text)
    by_words = await matching(http, terms, lang, n, ignore=generic_for(topic_text))
    tagged = await tag_feeds(http, terms[:4]) if lang == "en" else []
    themed.sort(key=lambda d: (bool(d.extra.get("event")), d.published or ""), reverse=True)  # раунды и запуски, затем свежие
    return _unique([*by_words, *tagged, *themed])[:n]


async def siliconangle(http: HttpClient, query: str, n: int = 20) -> list[RawDoc]:
    url = SILICONANGLE.format(q=quote(query.replace('"', "")).replace("%20", "+"))
    if not await robots.allowed(http, url):
        _blocked(http, url)
        return []
    text = await http.get(url, as_json=False)
    feed = feedparser.parse(text)
    docs = []
    for e in feed.entries[:n]:
        title = clean(e.get("title"), 400)
        if not title:
            continue
        snippet = clean(re.sub(r"<[^>]+>", " ", e.get("summary", "")), 800)
        docs.append(
            RawDoc(
                url=re.sub(r"\?utm_.*$", "", e.get("link", "")),
                title=title,
                snippet=snippet,
                published=_date(e.get("published")),
                source_name="SiliconANGLE",
                source_type="news",
                language="en",
                collector="siliconangle",
                extra={"publisher_domain": "siliconangle.com", "event": event_of(f"{title} {snippet}")},
            )
        )
    return [d for d in docs if d.url]
