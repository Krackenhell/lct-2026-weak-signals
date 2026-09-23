"""Типизация источников и уровень доверия (требование ТЗ: наименование, ссылка, дата, тип, язык, доверие).

Правила прозрачные и детерминированные, чтобы жюри могло проверить критерии.
"""
from urllib.parse import urlparse

from app.collectors.base import RawDoc

TYPE_RU = {
    "science": "Научная публикация",
    "preprint": "Препринт",
    "news": "СМИ / новости",
    "press": "Пресс-релиз / блог компании",
    "repository": "Репозиторий кода",
    "community": "Профессиональное сообщество",
    "reference": "Энциклопедия / справочник",
    "patent": "Патент",
    "regulator": "Госорган / регулятор",
    "dataset": "Датасет организатора",
}

TRUST_RU = {"high": "Высокий", "medium": "Средний", "low": "Пониженный"}

# Домены с высоким доверием: регуляторы, международные организации, научные издатели, ведущие отраслевые СМИ.
HIGH_DOMAINS = (
    ".gov", ".gov.uk", ".europa.eu", ".edu", ".ac.uk", "cbr.ru", "gov.ru", "bis.org", "imf.org", "worldbank.org",
    "oecd.org", "nist.gov", "iso.org", "nature.com", "science.org", "ieee.org", "acm.org", "springer.com",
    "sciencedirect.com", "arxiv.org", "reuters.com", "ft.com", "bloomberg.com", "wsj.com", "economist.com",
    "kommersant.ru", "vedomosti.ru", "rbc.ru", "interfax.ru", "tass.ru",
)
MEDIUM_DOMAINS = (
    "techcrunch.com", "theverge.com", "wired.com", "zdnet.com", "siliconangle.com", "venturebeat.com",
    "theregister.com", "securityweek.com", "coindesk.com", "finextra.com", "habr.com", "cnews.ru", "tadviser.ru",
    "forbes.com", "forbes.ru", "spectrum.ieee.org", "technologyreview.com", "arstechnica.com", "semianalysis.com",
)
PRESS_MARKERS = ("prnewswire", "businesswire", "globenewswire", "accesswire", "einpresswire", "newswire", "/press", "/news/press", "press-release", "pressrelease")
LOW_DOMAINS = ("medium.com", "substack.com", "linkedin.com", "twitter.com", "x.com", "reddit.com", "t.me", "youtube.com", "facebook.com", "vc.ru", "dzen.ru")


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def classify(doc: RawDoc) -> tuple[str, str, str]:
    """Возвращает (source_type, trust_level, trust_reason)."""
    url = doc.url.lower()
    dom = _domain(url)

    if doc.source_type == "science":
        return "science", "high", "Научная публикация с метаданными OpenAlex/DOI"
    if doc.source_type == "preprint":
        return "preprint", "medium", "Препринт: научный текст без рецензирования"
    if doc.source_type == "repository":
        return "repository", "medium", "Открытый код: подтверждает инженерную активность, но не зрелость"
    if doc.source_type == "community":
        return "community", "low", "Обсуждение в сообществе: первичный индикатор, требует подтверждения"
    if doc.source_type == "dataset":
        return "dataset", "medium", "Материал из датасета организатора; первоисточник по ссылке"

    if any(m in url for m in PRESS_MARKERS):
        return "press", "low", "Пресс-релиз: рекламный материал, не может быть единственным основанием"
    if dom.endswith((".gov", ".gov.ru", ".europa.eu")) or dom in ("cbr.ru", "bis.org", "nist.gov", "imf.org"):
        return "regulator", "high", "Официальный сайт госоргана / международной организации"
    if any(dom == d or dom.endswith("." + d) or (d.startswith(".") and dom.endswith(d)) for d in HIGH_DOMAINS):
        return doc.source_type, "high", "Авторитетное издание или организация из списка доверенных"
    if any(dom == d or dom.endswith("." + d) for d in MEDIUM_DOMAINS):
        return doc.source_type, "medium", "Профессиональное отраслевое СМИ"
    if any(dom == d or dom.endswith("." + d) for d in LOW_DOMAINS):
        return "community", "low", "Блог / соцсеть: пониженное доверие, нужно независимое подтверждение"
    return doc.source_type, "medium" if doc.source_type == "news" else "low", "Источник вне списков доверия: оценивается по совокупности подтверждений"
