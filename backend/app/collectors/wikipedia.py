"""Википедия как индикатор массовой известности: есть ли статья и сколько у неё просмотров.

Устоявшаяся статья с большим трафиком — признак зрелой, общеизвестной технологии.
"""
import re
from datetime import date, timedelta
from urllib.parse import quote

from app.collectors.http import HttpClient

SEARCH = "https://en.wikipedia.org/w/api.php"
VIEWS = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/user/{title}/monthly/{start}/{end}"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", s.lower()).strip()


RU_API = "https://ru.wikipedia.org/w/api.php"
# Слова запроса, которые не являются названием технологии и только мешают поиску статьи.
RU_STOP = {"технологии", "технология", "технологий", "перспективные", "перспективы", "решения", "решений", "слабые", "сигналы",
           "новые", "новых", "развитие", "применение", "применения", "системы", "методы", "направления", "сфере", "области",
           "отрасли", "дело", "инновации", "тренды", "современные", "будущее", "использование", "рынок", "основе"}


async def translate_ru(http: HttpClient, text: str, limit: int = 2) -> list[str]:
    """Русские термины запроса → английские через межъязыковые ссылки Википедии (без LLM).

    Нужен, когда LLM недоступна или вернула испорченный план: англоязычные научные базы по русской фразе
    ничего не находят (запрос «газлифт в газоконденсатных скважинах» без перевода давал 18 документов).
    Пробуем пары соседних слов, затем отдельные слова; статья принимается, только если её заголовок начинается
    с основы слова запроса (иначе поиск подставляет случайные статьи вроде «Нефть»)."""
    words = [w for w in re.findall(r"[а-яё]{4,}", text.lower()) if w not in RU_STOP]
    nouns = [w for w in words if not ADJ.search(w)]
    adjectives = [w for w in words if ADJ.search(w)]
    out: list[str] = []
    # Сначала существительные (обычно это и есть термин: «газлифт», «графен»); прилагательные — по основе слова и только
    # если существительных не нашлось («микрофлюидные» → «микрофлюид*» → «Микрофлюидика»): иначе «многослойного»
    # превращалось бы в «многослойный перцептрон».
    for query, stem in [(w, w) for w in nouns[:3]] + ([(f"intitle:{w[:-3]}*", w) for w in adjectives[:2]] if not nouns else []):
        en = await _english_title(http, query, stem)
        if en and en.lower() not in (o.lower() for o in out):
            out.append(en)
        if len(out) >= limit:
            break
    return out


ADJ = re.compile(r"(ый|ий|ой|ая|яя|ое|ее|ые|ие|ого|его|ому|ему|ым|им|ых|их|ую|юю|ными|ными)$")


async def _english_title(http: HttpClient, query: str, stem: str) -> str:
    """Английское название статьи русской Википедии; если английской статьи нет — английская метка Wikidata."""
    data = await http.get(RU_API, params={"action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"})
    titles = [h.get("title", "") for h in (data.get("query") or {}).get("search", [])]
    titles = [t for t in titles if t.lower()[:5] == stem[:5]]  # заголовок начинается с основы слова запроса
    # Несколько подходящих статей: у «Газлифт» (страница значений) английской версии нет, у «Газлифт (нефтедобыча)» — есть метка.
    for title in titles:
        info = await http.get(RU_API, params={"action": "query", "prop": "langlinks|pageprops", "lllang": "en", "titles": title,
                                              "redirects": 1, "format": "json"})
        for page in ((info.get("query") or {}).get("pages") or {}).values():
            if "disambiguation" in (page.get("pageprops") or {}):
                continue
            for link in page.get("langlinks") or []:
                return re.sub(r"\s*\(.*?\)", "", link.get("*", "")).strip()
            qid = (page.get("pageprops") or {}).get("wikibase_item")
            if qid:
                wd = await http.get("https://www.wikidata.org/w/api.php",
                                    params={"action": "wbgetentities", "ids": qid, "props": "labels", "languages": "en", "format": "json"})
                label = (((wd.get("entities") or {}).get(qid) or {}).get("labels") or {}).get("en", {}).get("value", "")
                if label:
                    return re.sub(r"\s*\(.*?\)", "", label).strip()
    return ""


async def lookup(http: HttpClient, phrase: str, as_of: date | None = None) -> dict:
    """{'exists': bool, 'title': str|None, 'monthly_views': float}

    as_of — дата среза: просмотры берутся за год до неё; статья считается существовавшей, если у неё были просмотры
    (иначе статья, написанная после среза, «протекла» бы в прошлое)."""
    data = await http.get(
        SEARCH,
        params={"action": "query", "list": "search", "srsearch": f'intitle:"{phrase}"', "srlimit": 3, "format": "json"},
    )
    hits = (data.get("query") or {}).get("search", [])
    target = _norm(phrase)
    title = None
    for h in hits:
        t = _norm(h.get("title", ""))
        if t == target or t.rstrip("s") == target.rstrip("s"):
            title = h["title"]
            break
    if not title:
        return {"exists": False, "title": None, "monthly_views": 0.0}
    end = (as_of or date.today()).replace(day=1) - timedelta(days=1)
    start = (end - timedelta(days=365)).replace(day=1)
    try:
        v = await http.get(
            VIEWS.format(title=quote(title.replace(" ", "_"), safe=""), start=start.strftime("%Y%m%d"), end=end.strftime("%Y%m%d"))
        )
        items = v.get("items", [])
        views = sum(i.get("views", 0) for i in items) / max(len(items), 1)
    except Exception:
        views = 0.0
    if as_of and views == 0:
        return {"exists": False, "title": None, "monthly_views": 0.0}
    return {"exists": True, "title": title, "monthly_views": views}
