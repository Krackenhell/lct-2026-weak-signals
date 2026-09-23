"""Задачи для LLM с жёсткой привязкой к найденным документам, и шаблонные запасные варианты."""
import json
import re

from app.llm.providers import BaseLLM, LLMResult, parse_json

SYSTEM_ANALYST = (
    "Ты — технологический аналитик банка. Работаешь ТОЛЬКО с предоставленными документами. "
    "Не добавляй фактов, которых нет в документах. Отвечай строго в запрошенном JSON-формате."
)

# Словарь для расширения запроса без LLM: широкие направления -> англоязычные поисковые темы.
DOMAIN_LEXICON = {
    r"финтех|финанс|банк|платеж|платёж|fintech|payment|bank": ["fintech", "digital payments", "tokenization banking", "AI agents payments", "stablecoin", "credit scoring", "anti-money laundering", "digital identity verification", "decentralized finance", "regtech compliance"],
    r"кибер|безопасн|защит|security|cyber": ["AI security", "LLM security", "prompt injection", "agent security", "post-quantum cryptography", "confidential computing", "model supply chain security", "deepfake detection", "zero trust AI"],
    r"робот|robot": ["robot learning", "humanoid robot", "robot manipulation", "vision-language-action", "legged robot", "soft robotics", "robot foundation model", "swarm robotics", "teleoperation"],
    r"edge|периферийн|iot|интернет вещей|устройств": ["edge AI", "on-device LLM", "TinyML", "neuromorphic", "in-sensor computing", "edge inference accelerator", "federated learning edge", "NPU"],
    r"инфраструктур|дата-центр|цод|чип|полупровод|hardware|infrastructure|datacenter|gpu": ["AI accelerator", "AI data center", "optical interconnect", "photonic computing", "memory disaggregation CXL", "KV cache", "inference optimization", "chiplet", "in-memory computing"],
    r"индустр|промышлен|производств|завод|industrial|manufactur": ["industrial AI", "AI manufacturing", "industrial foundation model", "predictive quality", "AI process control", "industrial agents", "generative design", "robotic welding"],
    r"\bии\b|искусственн|нейросет|машинн|\bai\b|artificial intelligence|llm|генератив": ["large language model", "AI agents", "multimodal model", "small language model", "reasoning model", "model compression", "AI evaluation", "agentic workflow"],
    r"энерг|energy|батар|аккумул": ["energy storage", "virtual power plant", "solid-state battery", "grid AI", "small modular reactor", "hydrogen electrolysis", "sodium-ion battery"],
    r"медиц|здрав|health|биотех|biotech|фарм": ["AI drug discovery", "digital pathology", "medical foundation model", "gene editing", "wearable diagnostics", "microrobots medicine"],
    r"квант|quantum": ["quantum error correction", "quantum sensing", "post-quantum cryptography", "quantum networking", "quantum-inspired algorithms"],
    r"космос|спутник|space|satellite": ["satellite edge computing", "orbital data center", "direct-to-device satellite", "space robotics", "in-orbit servicing"],
    r"транспорт|авто|логист|transport|mobility|logistic": ["autonomous trucking", "vehicle-to-grid", "drone logistics", "AI logistics optimization", "event camera automotive"],
    r"ритейл|торгов|retail|e-commerce|commerce": ["agentic commerce", "AI shopping agent", "retail computer vision", "dynamic pricing AI"],
    r"материал|material|химия|chemistry": ["AI materials discovery", "self-driving laboratory", "metamaterials", "self-healing materials"],
    r"агро|сельск|agri|food": ["precision agriculture AI", "agricultural robotics", "vertical farming", "alternative protein"],
}


def fallback_plan(query: str) -> dict:
    q = query.lower()
    topics: list[str] = []
    for pattern, terms in DOMAIN_LEXICON.items():
        if re.search(pattern, q):
            topics += [t for t in terms if t not in topics]
    latin = re.findall(r"[a-zA-Z][a-zA-Z0-9\- ]{2,}", query)
    topics = [t.strip() for t in latin if t.strip()] + topics
    if not topics:
        topics = [query]
    return {"topic_en": topics[0], "subqueries": topics[:10], "ru_terms": [query], "generated_by": "lexicon"}


async def plan_query(llm: BaseLLM, query: str) -> tuple[dict, LLMResult | None]:
    prompt = (
        f"Запрос аналитика: «{query}».\n"
        "Сформируй план поиска РАННИХ технологических сигналов (новые технические подходы последних 1-2 лет) в научных и отраслевых источниках. "
        "Не включай зрелые общие темы вроде «AI in banking», «blockchain», «biometrics», «machine learning». "
        "Верни JSON: {\"topic_en\": краткое название области на английском, "
        "\"subqueries\": 10 англоязычных поисковых фраз по 2-4 слова, каждая — узкое новое направление внутри области "
        "(например для финтеха: «agentic payments», «tokenized deposits», «zero-knowledge KYC»), "
        "\"ru_terms\": 3 русскоязычные поисковые фразы}. Не называй конкретные компании."
    )
    res = await llm.complete(SYSTEM_ANALYST, prompt, temperature=0.3, max_tokens=600)
    data = parse_json(res.text) if res.ok else None
    if isinstance(data, dict) and data.get("subqueries"):
        base = fallback_plan(query)
        # Половина подтем — от LLM (новые узкие направления), половина — из проверенного словаря области.
        subs = [s for s in data["subqueries"] if isinstance(s, str)][:6]
        data["subqueries"] = subs + [t for t in base["subqueries"] if t not in subs][: max(0, 12 - len(subs))]
        data["generated_by"] = f"{res.provider}:{res.model}"
        return data, res
    return fallback_plan(query), res if llm.provider != "none" else None


async def extract_candidates(llm: BaseLLM, topic: str, docs: list[dict]) -> tuple[list[dict], LLMResult]:
    """Извлекает названия конкретных технологий из пачки документов (со ссылками на номера документов)."""
    listing = "\n".join(f"[{i}] {d['title']}. {d.get('snippet', '')[:260]}" for i, d in enumerate(docs))
    prompt = (
        f"Область: {topic}.\nДокументы:\n{listing}\n\n"
        "Выдели КОНКРЕТНЫЕ технологии или технические подходы, которые обсуждаются в документах "
        "(например «tokenized deposits», «optical circuit switching», «machine unlearning»), а не общие области "
        "(не «AI», не «blockchain», не «robotics»), не компании и не продукты. Объединяй синонимы. "
        "Верни JSON-массив до 15 объектов: {\"name_en\": 2-6 слов на английском, \"name_ru\": название на русском, "
        "\"docs\": [номера документов, где она упоминается]}."
    )
    res = await llm.complete(SYSTEM_ANALYST, prompt, temperature=0.1, max_tokens=1500)
    data = parse_json(res.text) if res.ok else None
    if not (isinstance(data, list) and all(isinstance(c, dict) for c in data)):
        data = _salvage_candidates(res.text)
    out = []
    if isinstance(data, list):
        for c in data:
            if not isinstance(c, dict) or not c.get("name_en"):
                continue
            ids = [i for i in c.get("docs", []) if isinstance(i, int) and 0 <= i < len(docs)]
            out.append({"name_en": str(c["name_en"]).strip(), "name_ru": str(c.get("name_ru") or "").strip(), "doc_idx": ids})
    return out, res


def _salvage_candidates(text: str) -> list[dict]:
    """Разбор «почти JSON», который иногда возвращают LLM: достаём поля регулярными выражениями."""
    out = []
    pattern = r'name_en\W+([^"\n]+?)\s*"\s*,\s*"?\s*name_ru\W+([^"\n]*?)\s*"(.*?)(?=name_en|\Z)'
    for m in re.finditer(pattern, text or "", flags=re.S):
        docs = [int(x) for x in re.findall(r"\d+", (re.search(r"docs\W*\[([^\]]*)\]", m.group(3)) or [None, ""])[1])]
        out.append({"name_en": m.group(1).strip(), "name_ru": m.group(2).strip(), "docs": docs})
    return out


async def write_dossier(llm: BaseLLM, query: str, name: str, evidence: list[dict], facts: dict) -> tuple[dict | None, LLMResult]:
    listing = "\n".join(
        f"[{i + 1}] ({e['type']}, {e['source']}, {e.get('date') or 'без даты'}) {e['title']}. {e.get('snippet', '')[:500]}" for i, e in enumerate(evidence)
    )
    prompt = (
        f"Запрос аналитика: «{query}». Технология: «{name}».\n"
        f"Наблюдаемые показатели: {json.dumps(facts, ensure_ascii=False)}\n"
        f"Документы:\n{listing}\n\n"
        "Подготовь аналитическую справку на русском языке ТОЛЬКО по этим документам, со ссылками вида [n] на номера документов. "
        "Верни JSON: {\"name_ru\": название технологии на русском, "
        "\"description\": что это за технология (2-3 предложения), "
        "\"advantage\": потенциальное преимущество (1-2 предложения), "
        "\"case_example\": конкретный пример применения или пилота из документов с указанием организации [n], "
        "\"bank_application\": как это может применить банк или его клиенты (1-2 предложения, пометь как гипотезу), "
        "\"why_weak_signal\": почему это ранний сигнал, а не зрелый тренд (2-3 предложения с опорой на показатели и документы), "
        "\"risks\": что может помешать развитию (1 предложение)}."
    )
    res = await llm.complete(SYSTEM_ANALYST, prompt, temperature=0.2, max_tokens=1400)
    data = parse_json(res.text) if res.ok else None
    return (data if isinstance(data, dict) else None), res


async def summarize_sources(llm: BaseLLM, docs: list[dict]) -> tuple[dict[int, str], LLMResult]:
    """Русские резюме иностранных источников одной пачкой: {индекс: резюме}."""
    listing = "\n".join(f"[{i}] {d['title']}. {d.get('snippet', '')[:400]}" for i, d in enumerate(docs))
    prompt = (
        f"Источники:\n{listing}\n\n"
        "Для каждого источника напиши резюме на русском языке в одно предложение (до 30 слов), только по тексту источника. "
        "Верни JSON-объект {\"номер\": \"резюме\"}."
    )
    res = await llm.complete(SYSTEM_ANALYST, prompt, temperature=0.1, max_tokens=2000)
    data = parse_json(res.text) if res.ok else None
    out = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                out[int(k)] = str(v)
            except (TypeError, ValueError):
                continue
    return out, res
