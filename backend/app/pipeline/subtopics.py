"""Растущие поднаправления темы по научной литературе — собственное решение, без LLM.

Зачем. На узких запросах («технологии многослойного графена», «газлифт», «микрофлюидика») языковая модель
предлагает общие подтемы вроде «graphene based sensors», а ранний сигнал — это то, что быстро растёт внутри
темы: «rhombohedral graphene», «chiral superconductivity», «velocity strings». OpenAlex размечает работы
ключевыми словами. Сравниваем, как часто ключевое слово встречается в работах по теме за последние 2 года
и за 2 года до этого, и оставляем только специфичные для темы (у общих слов вроде «thermal radiation» или
«random forest» работы по теме — малая доля всех их работ).

Шаги:
1. Ключевой термин на английском: из плана LLM без общих слов («technologies», «applications»);
   длинная фраза укорачивается до части, по которой в OpenAlex есть работы («gas lift in gas condensate
   wells» → «gas lift»); без LLM — перевод через межъязыковые ссылки Википедии.
2. Растущие ключевые слова темы с проверкой специфичности.
Найденные поднаправления становятся поисковыми фразами корпуса и отдельными кандидатами.
"""
import math
import re
from datetime import date

from app.collectors import openalex, wikipedia
from app.collectors.http import HttpClient, SourceError

GENERIC_TAIL = {"technology", "technologies", "innovation", "innovations", "application", "applications", "research", "solutions",
                "systems", "devices", "advances", "trends", "development", "industry", "sector", "techniques", "methods"}
GENERIC_HEAD = {"emerging", "advanced", "new", "novel", "modern", "future", "promising", "next", "generation", "smart"}
# Ключевые слова, которые встречаются почти в любой области и ничего не говорят о направлении.
GENERIC_KW = {"artificial intelligence", "machine learning", "deep learning", "neural network", "neural networks", "large language models",
              "random forest", "transfer learning", "risk assessment", "predictive maintenance", "optimal control", "heat transfer",
              "mass transfer", "heat and mass transfer", "oxidative stress", "clinical translation", "raman spectroscopy", "case study",
              "systematic review", "life cycle assessment", "sustainable development", "operational cost reduction", "corrosion resistance"}
PREP = r"\b(?:in|for|of|on|with|using|based|via|at|from|and)\b"
MIN_WORKS_CORE = 30  # меньше работ за 4 года — по фразе не найти рост, укорачиваем
MIN_SPECIFICITY = 0.05  # доля работ ключевого слова, в которых есть тема (0,04 пропускало «thermal radiation» в микрофлюидике)
MAX_CHECK = 15  # проверка специфичности — по запросу на слово; больше 15 не проверяем (скорость)


# Обёртки, которые план GigaChat переносит из формулировки запроса в саму тему: «Early Signals in AI Cybersecurity»,
# «Early stage Robotics», «Early Technological Signals in FinTech». С ними поиск по литературе идёт по словам «early signals»
# (растущее поднаправление «second messengers» для безопасности ИИ), а не по предмету — широкие темы теряли кандидатов (замер 20.10).
META_WRAP = re.compile(
    r"^\s*(?:(?:early|weak|emerging|promising|prospective|perspective|future|new)[\s-]+)*"
    r"(?:(?:stage|technological|technology|tech|tech-?nology)[\s-]+)*"
    r"(?:signals?|trends?|solutions?|technologies|innovations?|opportunities|directions?)\s+(?:in|of|for|within|across)\s+",
    re.I,
)
META_HEAD = re.compile(r"^\s*(?:(?:early[\s-]+stage|(?:early|weak)[\s-]+signals?|emerging|promising|prospective)\s+)+", re.I)


def clean_topic(topic_en: str) -> str:
    """«Early Signals in AI Cybersecurity» → «AI Cybersecurity»; «Early stage Robotics» → «Robotics»; обычная тема — без изменений."""
    t = META_WRAP.sub("", topic_en or "")
    t = META_HEAD.sub("", t).strip()
    return t or (topic_en or "")


def core_term(topic_en: str) -> str:
    """«microfluidics technologies» → «microfluidics»; «emerging multilayer graphene technologies» → «multilayer graphene»."""
    words = re.sub(r"[_\-–—/]+", " ", topic_en or "").split()
    while words and words[-1].lower() in GENERIC_TAIL:
        words.pop()
    while words and words[0].lower() in GENERIC_HEAD:
        words.pop(0)
    return " ".join(words).strip()


def _shorter(term: str) -> list[str]:
    """Варианты фразы от полной к короткой: часть до предлога без общих слов
    («gas lift technology in gas and condensate wells» → «gas lift»)."""
    out = [core_term(term)]
    head = core_term(re.split(PREP, term, maxsplit=1)[0].strip())
    if head and head not in out:
        out.append(head)
    return [x for x in out if x]


async def resolve_core(http: HttpClient, topic_en: str, query: str) -> str:
    """Ключевой термин, по которому в OpenAlex есть работы. Без английского термина — перевод через Википедию."""
    year = date.today().year
    from_llm = bool(re.search(r"[a-z]", topic_en or "", re.I))
    variants = _shorter(topic_en) if from_llm else [core_term(t) for t in await wikipedia.translate_ru(http, query)]
    best = ""
    for v in [x for x in variants if x]:
        try:
            n = await openalex.count(http, f'{openalex._phrase_filter(v)},publication_year:{year - 3}-{year}')
        except SourceError:
            return v if from_llm else ""  # OpenAlex недоступен: термину LLM верим, непроверенному переводу — нет
        if n >= MIN_WORKS_CORE:
            return v
        best = best or v
    return best if from_llm else ""  # перевод без подтверждения литературой не используем


async def emerging(http: HttpClient, core: str, k: int = 6) -> list[dict]:
    """Ключевые слова, доля которых в работах по теме выросла сильнее всего, и только специфичные для темы."""
    if not core:
        return []
    y = date.today().year
    recent = await openalex.keyword_groups(http, core, f"{y - 1}-{y}")
    prior = await openalex.keyword_groups(http, core, f"{y - 3}-{y - 2}")
    tr = sum(n for _, n in recent.values()) or 1
    tp = sum(n for _, n in prior.values()) or 1
    rows = []
    for key, (name, n) in recent.items():
        low = name.lower()
        if n < 5 or len(low.split()) < 2 or low in GENERIC_KW or low == core.lower() or core.lower() in low and len(low.split()) <= len(core.split()) + 1:
            continue
        p = prior.get(key, ("", 0))[1]
        growth = math.log((n / tr + 2e-3) / (p / tp + 2e-3))
        if growth > 0.3:
            rows.append((growth, n, p, key, name))
    rows.sort(reverse=True)
    out = []
    for growth, n, p, key, name in rows[:MAX_CHECK]:
        kid = key.rsplit("/", 1)[-1]
        try:
            total = await openalex.count(http, f"keywords.id:{kid},publication_year:{y - 1}-{y}")
        except SourceError:
            continue
        spec = n / total if total else 0.0
        if total >= 10 and spec >= MIN_SPECIFICITY:
            out.append({"keyword": name.lower(), "recent": n, "prior": p, "growth": round(growth, 2), "specificity": round(spec, 3)})
    out.sort(key=lambda r: (-r["growth"], -r["specificity"]))
    return out[:k]


# Модные слова, которые LLM приставляет к любой теме («artificial intelligence for gaslift optimization»): такие подтемы
# приводят в корпус общие новости про ИИ, и кандидаты «agentic ai», «edge ai» вытесняют саму тему.
BUZZ = re.compile(r"\b(artificial intelligence|machine learning|deep learning|quantum computing|blockchain|generative ai|ai|ml|llms?|"
                  r"digital twins?|internet of things|iot|big data|metaverse)\b", re.I)
AI_QUERY = re.compile(r"\bии\b|искусственн|нейросет|машинн\w* обучен|\bai\b|\bml\b|llm|квант|блокчейн|данн|цифров", re.I)


def drop_buzz(subqueries: list[str], query: str) -> list[str]:
    """Подтемы LLM без модных приставок — если сам запрос не про ИИ, квантовые вычисления, данные или блокчейн."""
    if AI_QUERY.search(query or ""):
        return subqueries
    return [s for s in subqueries if not BUZZ.search(s)]


def literature_candidates(found: list[dict], corpus) -> list[dict]:
    """Растущие поднаправления — сразу кандидаты, со ссылками на документы корпуса, где они упоминаются."""
    out = []
    for e in found:
        kw = e["keyword"]
        idx = [i for i, d in enumerate(corpus) if kw in f"{d.title} {d.snippet}".lower()][:8]
        out.append({"name_en": kw, "name_ru": "", "doc_idx": idx, "method": "literature-growth", "growth": e})
    return out
