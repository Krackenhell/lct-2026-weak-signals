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


QUESTION_RU = {
    "specific_tech": "Конкретная технология, а не общая область",
    "mass_adoption": "Массовое внедрение",
    "market_leaders": "Сформированный рынок с лидерами",
    "standard": "Действующий отраслевой стандарт",
    "early_stage": "Ранняя стадия (исследования, пилоты)",
    "independent": "Независимые участники",
    "hype": "Маркетинговый шум",
    "novelty": "Новизна",
    "benefit": "Конкретное преимущество",
    "textbook": "Устоявшаяся (учебниковая) идея",
    "maturity": "Зрелость (0 — исследование, 1 — мейнстрим)",
    "relevance": "Релевантность запросу",
    "evidence_match": "Источники действительно про эту технологию",
    "product_name": "Название конкретного продукта / компании",
    "is_technology": "Это инновация (а не документ, явление, организация)",
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
