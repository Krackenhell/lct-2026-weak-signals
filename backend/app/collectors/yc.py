"""Стартапы Y Combinator: открытое зеркало публичного каталога YC (yc-oss, ~6300 компаний с 2005 года).

Зачем: акселератор отбирает около 1–2% заявок и вкладывает деньги в каждую компанию набора, поэтому
стартап YC, который строит технологию, — это ранний рыночный сигнал «деньги пошли в направление».
У каждой компании есть набор (Winter 2021 и т. п.), поэтому по технологии получается ряд «сколько стартапов
по годам набора» — он доступен и для прошлых лет (машина времени). Ограничение: описание компании —
текущее, а не на момент набора; поэтому ряд YC в обучение модели не входит, только в паспорт и проверку.

Каталог — один JSON (~10 МБ), кэшируется на 72 часа и в памяти процесса.
"""
import asyncio
import re

from app.collectors.base import RawDoc, clean
from app.collectors.http import HttpClient

URL = "https://yc-oss.github.io/api/companies/all.json"
SEASON = {"winter": "01", "spring": "04", "summer": "06", "fall": "09", "x": "01"}
_DATA: list[dict] | None = None


_LOCKS: dict[int, asyncio.Lock] = {}  # своя блокировка на каждый цикл событий (тесты создают новые)


async def load(http: HttpClient) -> list[dict]:
    """Каталог загружается один раз: параллельные проверки кандидатов ждут первую загрузку."""
    global _DATA
    lock = _LOCKS.setdefault(id(asyncio.get_running_loop()), asyncio.Lock())
    async with lock:
        if _DATA is None:
            data = await http.get(URL)
            _DATA = [c for c in data if isinstance(c, dict)] if isinstance(data, list) else []
    return _DATA


def batch_date(batch: str | None) -> str | None:
    m = re.match(r"(\w+)\s+(\d{4})", batch or "")
    if not m:
        return None
    return f"{m.group(2)}-{SEASON.get(m.group(1).lower(), '01')}-01"


def _text(c: dict) -> str:
    """Текст компании в нижнем регистре; считается один раз и хранится в записи (каталог — 6300 компаний)."""
    t = c.get("_text")
    if t is None:
        tags = c.get("tags") if isinstance(c.get("tags"), list) else []
        t = c["_text"] = f"{c.get('one_liner') or ''} {c.get('long_description') or ''} {' '.join(tags)}".lower()
    return t


def _words(phrase: str) -> list[str]:
    words = [w for w in re.findall(r"[a-z0-9]+", phrase.lower()) if len(w) > 1 or w.isdigit()]
    return [w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w for w in words]  # payments → payment(s)


def _pattern(phrase: str) -> re.Pattern:
    """Фраза до трёх слов — точная последовательность слов («know your agent» не равно «know … agent»);
    длиннее — все слова в любом порядке. Множественное число допускается («payments» = «payment»)."""
    words = _words(phrase)
    if not words:
        return re.compile(r"(?!)")
    if len(words) <= 3:
        return re.compile(r"\b" + r"[\s\-]+".join(rf"{re.escape(w)}(s|es)?" for w in words) + r"\b")
    return re.compile("".join(rf"(?=.*\b{re.escape(w)}(s|es)?\b)" for w in words), re.S)


def find(companies: list[dict], phrase: str) -> list[dict]:
    """Скорость: сначала дешёвая проверка «все слова есть в тексте», регулярное выражение — только для прошедших
    (раньше 30 кандидатов × 2 поиска × 6300 компаний проверялись тяжёлым выражением и блокировали обработку)."""
    words, pat = _words(phrase), _pattern(phrase)
    if not words:
        return []
    return [c for c in companies if all(w in _text(c) for w in words) and pat.search(_text(c))]


async def search(http: HttpClient, phrase: str, n: int = 5, min_year: int | None = None) -> list[RawDoc]:
    found = find(await load(http), phrase)
    found = [c for c in found if batch_date(c.get("batch")) and (min_year is None or int(batch_date(c["batch"])[:4]) >= min_year)]
    found.sort(key=lambda c: batch_date(c["batch"]), reverse=True)
    docs = []
    for c in found[:n]:
        docs.append(RawDoc(
            url=c.get("url") or f"https://www.ycombinator.com/companies/{c.get('slug')}",
            title=clean(f"{c.get('name')}: {c.get('one_liner') or ''}", 400),
            snippet=clean(f"Стартап Y Combinator, набор {c.get('batch')}, статус {c.get('status')}. {c.get('long_description') or ''}", 800),
            published=batch_date(c.get("batch")),
            source_name="Y Combinator", source_type="startup", language="en", collector="yc",
            extra={"event": "funding", "batch": c.get("batch"), "website": c.get("website"), "publisher_domain": "ycombinator.com"},
        ))
    return docs


async def yearly(http: HttpClient, phrase: str) -> dict[str, int]:
    """Число стартапов YC по году набора, которые описывают технологию."""
    out: dict[str, int] = {}
    for c in find(await load(http), phrase):
        d = batch_date(c.get("batch"))
        if d:
            out[d[:4]] = out.get(d[:4], 0) + 1
    return dict(sorted(out.items()))
