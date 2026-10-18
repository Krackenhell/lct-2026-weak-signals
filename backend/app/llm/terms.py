"""Русские названия технологий: глоссарий и проверка калек (собственное решение, без дополнительного вызова LLM).

Эксперты финала отметили неудачный перевод («закаливание подсказок» вместо prompt hardening). В базе нашлись и другие
типовые ошибки GigaChat: слова, склеенные дефисом («искусственный-интеллект-в-промышленной-автоматизации»), кальки
(«на краях» вместо «на периферии», «рамки» вместо «фреймворки», «основополагающие модели» вместо «фундаментальные модели»,
«Обусловленный ИИ» вместо «воплощённый ИИ»). Порядок:
1. глоссарий принятых терминов — передаётся GigaChat в промпте и применяется к точным совпадениям;
2. правила исправляют склейку и известные кальки;
3. если подозрительная калька осталась — показываем английский термин: лучше точный оригинал, чем неверный перевод.
"""
import re

# Принятые в русскоязычных IT-изданиях и научных статьях термины (EN → RU). Ключи — в нижнем регистре.
GLOSSARY = {
    "prompt hardening": "защита промптов от атак",
    "prompt injection": "промпт-инъекции",
    "prompt-injection detection": "обнаружение промпт-инъекций",
    "prompt engineering": "промпт-инжиниринг",
    "jailbreak": "джейлбрейк",
    "red teaming": "ред-тиминг",
    "embodied ai": "воплощённый ИИ",
    "embodied artificial intelligence": "воплощённый ИИ",
    "agentic ai": "агентный ИИ",
    "ai agents": "ИИ-агенты",
    "foundation models": "фундаментальные модели",
    "foundation model": "фундаментальная модель",
    "federated learning": "федеративное обучение",
    "edge ai": "периферийный ИИ",
    "edge computing": "периферийные вычисления",
    "on-device llm inference": "инференс LLM на устройстве",
    "spiking neural networks": "импульсные нейронные сети",
    "spiking neural network": "импульсная нейронная сеть",
    "digital twin": "цифровой двойник",
    "smart contract": "смарт-контракт",
    "fine-tuning": "дообучение",
    "retrieval-augmented generation": "генерация с дополнением из поиска (RAG)",
    "knowledge distillation": "дистилляция знаний",
    "self-driving laboratories": "автономные лаборатории",
    "multilayer graphene": "многослойный графен",
    "twisted multilayer graphene": "скрученный многослойный графен",
    "twisted bilayer graphene": "скрученный двухслойный графен",
    "rhombohedral graphene": "ромбоэдрический графен",
    "moire superlattices": "муаровые сверхрешётки",
    "moiré superlattices": "муаровые сверхрешётки",
    "chern insulator": "черновский изолятор",
    "fractional chern insulator": "дробный черновский изолятор",
    "chiral superconductivity": "хиральная сверхпроводимость",
    "perovskite tandem solar cells": "перовскитные тандемные солнечные элементы",
    "microfluidic chips": "микрофлюидные чипы",
    "organ-on-a-chip": "орган-на-чипе",
    "tokenized deposits": "токенизированные депозиты",
    "stablecoin": "стейблкоин",
}

# (шаблон кальки, исправление или None — исправить нельзя, показываем английский термин)
CALQUES: list[tuple[str, str | None]] = [
    (r"\bна\s+края[хм]\b|\bна\s+краю\b", "на периферии"),
    (r"\bкраевы[хме]\s+(вычислени\w*)", r"периферийных \1"),
    (r"\bрамк[иа]\b(?=.*\b(ии|ai|вычислен|периферий))", "фреймворки"),
    (r"\bосновополагающ\w*\s+модел\w*", "фундаментальные модели"),
    (r"\bна\s+всплесках\b", "импульсные"),
    (r"\bагентский\b", "агентный"), (r"\bагентская\b", "агентная"), (r"\bагентское\b", "агентное"), (r"\bагентские\b", "агентные"),
    (r"\bподсказ\w*", "промптов"),
    (r"\bзакаливани\w*|\bзакалк\w*", None),
    (r"\bобусловленн\w*\s+ии\b", "воплощённый ИИ"),
    (r"\bтелесн\w*", None),
    (r"\bинтеллекуальн\w*|\bобученое\b|\bглубинное[\s-]+обучен", None),  # частые опечатки и сбои согласования
    (r"\bумное\s+менеджмент\w*", None),
    (r"\bмультиграфен\w*", "многослойный графен"),
    (r"\bчирн\w*", "черновский"),
]

# Кальки, которые исправляются только при определённом английском слове в оригинале: «силиконовый» верно для silicone,
# но не для silicon (кремний); «фракционный» верно в химии, но fractional в физике — «дробный».
CONDITIONAL: list[tuple[str, str, str]] = [
    ("silicon", r"\bсиликонов(ый|ая|ое|ые|ого|ой|ых|ым|ую)\b", r"кремниев\1"),
    ("fractional", r"\bфракционн(ый|ая|ое|ые|ого|ой|ых|ым|ую)\b", r"дробн\1"),
]

CYR = re.compile(r"[а-яё]", re.I)


ADJ_END = r"(?:ый|ий|ой|ая|яя|ое|ее|ые|ие|ых|их|ого|его|ому|ему|ым|им|ую|юю)"
PREP = r"(?:в|во|на|для|с|со|по|и|из|от|к|о|об|при|без)"


def _unglue(s: str) -> str:
    """«искусственный-интеллект-в-промышленности», «федеративное-обучение» → слова через пробел.
    Дефис убирается только между русскими словами, если слева прилагательное или с одной из сторон предлог.
    Составные слова («робот-компаньон», «квантово-инспирированное», «смарт-контракт») и латиница («edge-инференс»,
    «compute-in-memory») не трогаем."""
    pair = re.compile(r"\b([а-яё]+)-(?=([а-яё]+)\b)", re.I)
    glued = len(pair.findall(s)) >= 2  # «системы-интрузионного-контроля»: склеена целая фраза

    def repl(m: re.Match) -> str:
        left = m.group(1)
        keep = left.lower() in COMPOUND_LEFT or left.lower().endswith(("о", "е")) and not re.search(ADJ_END + "$", left, re.I)
        if keep:
            return m.group(0)
        if glued or re.search(ADJ_END + "$", left, re.I) or re.fullmatch(PREP, left, re.I) or re.fullmatch(PREP, m.group(2), re.I):
            return left + " "
        return m.group(0)

    return pair.sub(repl, s)


# Левая часть устойчивых составных слов: «литий-ионный», «робот-компаньон», «смарт-контракт».
COMPOUND_LEFT = {"ии", "литий", "натрий", "калий", "робот", "роботы", "смарт", "мульти", "супер", "интернет", "онлайн", "офлайн", "бизнес"}
MIXED = re.compile(r"\b(?=\w*[а-яё])(?=\w*[a-z])\w+\b", re.I)  # «адversarial», «Спiking»: сбой генерации


def normalize_name_ru(name_en: str, name_ru: str | None) -> str:
    """Русское название для показа: глоссарий → исправление калек → английский термин, если перевод неисправим."""
    en = (name_en or "").strip()
    key = en.lower()
    if key in GLOSSARY:
        return GLOSSARY[key]
    ru = re.sub(r"\s+", " ", (name_ru or "").strip())
    if not ru:
        return ""
    if MIXED.search(ru):
        return en
    ru = _unglue(ru)
    for pattern, fix in CALQUES:
        if re.search(pattern, ru, flags=re.I):
            if fix is None:
                return en
            ru = re.sub(pattern, fix, ru, flags=re.I)
    low_en = key.replace("silicone", "")  # silicone (силикон) — не silicon (кремний)
    for word, pattern, fix in CONDITIONAL:
        if word in low_en:
            ru = re.sub(pattern, fix, ru, flags=re.I)
    return ru


def glossary_hint(limit: int = 18) -> str:
    """Подсказка для промпта GigaChat: принятые переводы терминов."""
    items = list(GLOSSARY.items())[:limit]
    return "; ".join(f"{k} — {v}" for k, v in items)
