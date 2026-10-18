"""Вопросы к decision-модели. Каждый ответ — отдельный интерпретируемый признак.

Вопросы сформулированы на английском: так decision-модели отвечают точнее.
Русские подписи используются в интерфейсе и объяснениях.
"""

MATURITY_LEVELS = [
    "Basic research or concept only",
    "Laboratory prototype or proof of concept",
    "Pilot projects or first field trials",
    "First commercial products with few customers",
    "Growing market with several competing vendors",
    "Mainstream, widely deployed and commoditized",
]

QUESTIONS = {
    "specific_tech": {
        "type": "noul",
        "instructions": "Is the SUBJECT a specific technology or technical approach, rather than a broad research field, a generic buzzword, a company or a single product brand?",
    },
    "mass_adoption": {
        "type": "noul",
        "instructions": "Does the evidence show the SUBJECT is already widely deployed in production by many organizations (mass adoption)?",
    },
    "market_leaders": {
        "type": "noul",
        "instructions": "Does the evidence show an established market for the SUBJECT with clear dominant vendors and stable competition?",
    },
    "standard": {
        "type": "noul",
        "instructions": "Is the SUBJECT itself an established industry standard, protocol or regulation that is already in wide use?",
    },
    "early_stage": {
        "type": "noul",
        "instructions": "Does the evidence mostly describe research, prototypes, pilots or first deployments of the SUBJECT?",
    },
    "independent": {
        "type": "noul",
        "instructions": "Is the SUBJECT pursued by several independent organizations (different research groups, companies or regulators), not by a single company?",
    },
    "hype": {
        "type": "noul",
        "instructions": "Is the evidence about the SUBJECT dominated by marketing claims, press releases or promotional language without technical substance?",
    },
    "novelty": {
        "type": "noul",
        "instructions": "Is the SUBJECT presented in the evidence as new, emerging or recently proposed?",
    },
    "benefit": {
        "type": "noul",
        "instructions": "Does the evidence describe a concrete practical advantage of the SUBJECT, such as lower cost, higher accuracy or a new capability?",
    },
    "textbook": {
        "type": "noul",
        "instructions": "Is the core idea of the SUBJECT a long-established concept in its field — covered in textbooks or in common use for more than 10 years — even if the evidence describes a new variant?",
    },
    "maturity": {
        "type": "score",
        "instructions": "What is the development stage of the SUBJECT according to the evidence?",
        "criteria": MATURITY_LEVELS,
    },
}

# Проверка, что доказательства действительно про предмет, а не про созвучные слова.
# В классификатор не входит (при обучении предмет задан точно), используется как фильтр.
EVIDENCE_MATCH = {
    "type": "noul",
    "instructions": "Do the EVIDENCE items actually discuss the SUBJECT as a technology (not just contain similar words)?",
}

PRODUCT_NAME = {
    "type": "noul",
    "instructions": "Is the SUBJECT the name of one specific company, product, app, token or project, rather than a type of technology that several organizations could build?",
}

IS_TECHNOLOGY = {
    "type": "noul",
    "instructions": "Is the SUBJECT an innovation — a technology, technical approach, or a new type of product, financial instrument or service model that several organizations could offer — as opposed to a book, document, code repository, dataset, a single organization, or a general market phenomenon or policy topic?",
}


# Вопрос о релевантности зависит от запроса и в классификатор не входит: используется для ранжирования.
def relevance_question(topic: str) -> dict:
    return {
        "type": "score",
        "instructions": f"How relevant is the SUBJECT to the topic '{topic}'?",
        "criteria": ["Unrelated", "Weakly related", "Related", "Core part of the topic"],
    }


# Релевантность к исходной формулировке аналитика: тема плана может «уехать» при расширении запроса,
# поэтому кандидат должен подходить и к теме, и к тому, что человек написал на самом деле.
def query_relevance_question(query: str, topic: str) -> dict:
    return {
        "type": "score",
        "instructions": f"The analyst literally asked (possibly in Russian): '{query}'. The search topic derived from it is '{topic}'. How relevant is the SUBJECT to what the analyst literally asked?",
        "criteria": ["Unrelated", "Weakly related", "Related", "Core part of the request"],
    }


# Самое «твёрдое» событие в доказательствах. Пока не входит в классификатор (нужен переопрос обучающей
# выборки: python -m app.ml.train --reask), используется в паспорте доказательств и в карточке.
EVENT_LEVELS = [
    "Only discussion, opinion or forecast",
    "Research paper or preprint",
    "Prototype or proof of concept",
    "Research grant or public funding",
    "Pilot project or field trial",
    "Product or open-source release",
    "Investment round, acquisition or spin-off",
]
EVENT_RU = ["только обсуждения", "научная статья / препринт", "прототип", "грант / госфинансирование", "пилот / испытания", "релиз продукта или открытого кода", "раунд инвестиций / сделка"]
EVENT = {
    "type": "score",
    "instructions": "What is the most concrete real-world event about the SUBJECT that the EVIDENCE reports?",
    "criteria": EVENT_LEVELS,
}
HARD_EVENT_LEVEL = 4  # пилот и выше — «твёрдое» событие


def event_label(value: float | None) -> tuple[int, str]:
    """value из нормализованного ответа (0..1) → номер уровня и русская подпись."""
    if value is None:
        return 0, EVENT_RU[0]
    level = int(round(float(value) * (len(EVENT_LEVELS) - 1)))
    level = max(0, min(level, len(EVENT_LEVELS) - 1))
    return level, EVENT_RU[level]


# Паспорт доказательств: decision-модель проверяет каждый документ отдельно, в том же вызове.
def doc_questions(n: int) -> dict:
    return {
        f"doc_{i}": {"type": "noul", "instructions": f"Does EVIDENCE item [{i}] actually describe the SUBJECT itself (not just similar words)?"}
        for i in range(1, n + 1)
    }


# Перекрёстная проверка досье: утверждения, написанные LLM, проверяет decision-модель.
def claim_questions(claims: list[str]) -> dict:
    return {
        f"claim_{i}": {"type": "noul", "instructions": f"Is the following STATEMENT supported by the EVIDENCE items? STATEMENT: {c}"}
        for i, c in enumerate(claims, 1)
    }


def count_items(state: str) -> int:
    """Сколько фрагментов доказательств поместилось в текст для decision-модели."""
    return sum(1 for line in state.splitlines() if line.startswith("[") and "]" in line[:6])


QUESTION_RU = {
    "specific_tech": "Конкретная технология, а не общая область",
    "mass_adoption": "Массовое внедрение",
    "market_leaders": "Сформированный рынок с лидерами",
    "standard": "Действующий отраслевой стандарт",
    "early_stage": "Ранняя стадия (исследования, пилоты)",
    "independent": "Независимые участники",
    "hype": "Преобладание рекламных материалов",
    "novelty": "Новизна",
    "benefit": "Конкретное преимущество",
    "textbook": "Устоявшаяся (учебниковая) идея",
    "maturity": "Зрелость (0 — исследование, 1 — мейнстрим)",
    "relevance": "Релевантность запросу",
    "evidence_match": "Источники действительно про эту технологию",
    "product_name": "Название конкретного продукта / компании",
    "is_technology": "Это инновация (а не документ, явление, организация)",
    "relevance_query": "Релевантность исходной формулировке запроса",
    "event": "Самое твёрдое событие (0 — обсуждения, 1 — раунд инвестиций)",
}


def build_state(subject: str, topic: str, evidence: list[dict], max_chars: int = 3500) -> str:
    """Текст для decision-модели: предмет оценки и пронумерованные фрагменты доказательств."""
    lines = [f"SUBJECT: {subject}"]
    if topic:
        lines.append(f"TOPIC OF INTEREST: {topic}")
    lines.append("EVIDENCE:")
    used = sum(len(x) for x in lines)
    for i, e in enumerate(evidence, 1):
        line = f"[{i}] ({e.get('type', '')}, {e.get('source', '')}, {e.get('date') or 'n.d.'}) {e.get('title', '')}. {e.get('snippet', '')[:420]}"
        if used + len(line) > max_chars:
            break
        lines.append(line)
        used += len(line)
    return "\n".join(lines)
