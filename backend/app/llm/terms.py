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
    "chern insulators": "черновские изоляторы",
    "high chern insulators": "черновские изоляторы с большим числом Черна",
    "high chern number insulators": "черновские изоляторы с большим числом Черна",
    "fractional chern insulator": "дробный черновский изолятор",
    "chiral superconductivity": "хиральная сверхпроводимость",
    "perovskite tandem solar cells": "перовскитные тандемные солнечные элементы",
    "microfluidic chips": "микрофлюидные чипы",
    "organ-on-a-chip": "орган-на-чипе",
    "tokenized deposits": "токенизированные депозиты",
    "stablecoin": "стейблкоин",
    # Примеры экспертов финала: графен и микрофлюидика.
    "intercalation": "интеркаляция",
    "graphene intercalation": "интеркаляция графена",
    "chemical vapor deposition": "химическое осаждение из газовой фазы (CVD)",
    "cvd graphene": "CVD-графен",
    "liquid phase exfoliation": "жидкофазная эксфолиация",
    "exfoliation": "эксфолиация (расслоение)",
    "lab-on-a-chip": "лаборатория на чипе",
    "lab on a chip": "лаборатория на чипе",
    "organ on a chip": "орган-на-чипе",
    "organs-on-chips": "органы-на-чипе",
    "droplet microfluidics": "капельная микрофлюидика",
    "digital microfluidics": "цифровая микрофлюидика",
    "paper-based microfluidics": "бумажная микрофлюидика",
    "inertial microfluidics": "инерционная микрофлюидика",
    "point-of-care testing": "диагностика по месту лечения",
    # Типовые ошибки 18.10 (кальки и инверсии смысла).
    "physically unclonable functions": "физически неклонируемые функции",
    "physical unclonable functions": "физически неклонируемые функции",
    "federated learning at the edge": "федеративное обучение на периферии",
    "prompt injection detection": "обнаружение промпт-инъекций",
    "quantum kernel svm": "квантовые ядра для метода опорных векторов",
    "quantum support vector machines": "квантовый метод опорных векторов",
    "solid-state batteries": "твердотельные аккумуляторы",
    "solid-state battery": "твердотельный аккумулятор",
    "perovskite solar cells": "перовскитные солнечные элементы",
    "neuromorphic computing": "нейроморфные вычисления",
    "gas lift": "газлифт",
    "gas lift optimization": "оптимизация газлифта",
    "tumor-educated platelets": "тромбоциты, изменённые опухолью (TEP)",
    "liquid biopsy": "жидкостная биопсия",
    "all-solid-state batteries": "полностью твердотельные аккумуляторы",
    "all-solid-state battery": "полностью твердотельный аккумулятор",
    "solid electrolytes": "твёрдые электролиты",
    "halide electrolytes": "галогенидные электролиты",
    "sulfide electrolytes": "сульфидные электролиты",
    "moire flat bands": "плоские зоны муаровых сверхрешёток",
    "moiré flat bands": "плоские зоны муаровых сверхрешёток",
    "moire fractional chern insulators": "муаровые дробные черновские изоляторы",
    "generalized wigner crystals": "обобщённые вигнеровские кристаллы",
    "wigner crystals": "вигнеровские кристаллы",
    "tetralayer graphene superconductivity": "сверхпроводимость четырёхслойного графена",
    "rhombohedral graphene multilayers": "многослойный ромбоэдрический графен",
    "superconductivity in multilayer graphene": "сверхпроводимость многослойного графена",
    "fractional quantum anomalous hall effect": "дробный квантовый аномальный эффект Холла",
    "multilayer graphene synthesis": "синтез многослойного графена",
    "3d resin printing": "3D-печать фотополимерными смолами",
    "microfluidic live-cell imaging": "микрофлюидная визуализация живых клеток",
    "live-cell imaging": "визуализация живых клеток",
    "label-free enrichment": "безметочное обогащение клеток",
    "cleanroom-free microfluidic chips": "микрофлюидные чипы без чистых помещений",
    "nanofluidic memristors": "нанофлюидные мемристоры",
    "elasto-inertial microfluidics": "эласто-инерционная микрофлюидика",
}

# Термины без устоявшегося русского перевода: показываем английский заголовок (с русской подписью, если она есть).
KEEP_EN = {"self-supervised learning", "over-the-air computation", "over-the-air federated learning", "strain stiffening",
           "in-context learning", "mixture of experts", "retrieval-augmented generation"}

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
    (r"\bчирн(?:овск|-?)?(ий|ая|ое|ие|их|ого|ой|ым|ими)\b", r"черновск\1"),  # с сохранением окончания: «черновские изоляторы»
    (r"\bчирн\w*", "черновский"),
    (r"\bинсулятор", "изолятор"),
    (r"\bчернов(ые|ых)\s+изолятор", r"черновские изолятор"),  # chern insulators («трансмерные черновые изоляторы», 20.10)
    (r"\bгазового\s+подъ[её]ма\b", "газлифта"),  # gas lift — «оптимизация газового подъёма» (20.10)
    (r"\bгазов\w+\s+подъ[её]м\w*", "газлифт"),
    (r"\bтуморо-?образованн\w*", None),  # tumor-educated — калька, показываем английский термин  # insulator — «изолятор» («высокие черновский инсуляторы», 19.10)
    (r"\bрезинов\w*\s+3[дdD]", None),  # «резиновая 3д-печать» (3d resin printing: resin — смола, не резина)
    (r"\bмикрожидкостн", "микрофлюидн"),  # microfluidic — в русской литературе «микрофлюидный» (живой прогон 19.10)
    (r"\bживо\w*\s+клеточн\w*\s+изображени\w*", None),  # live-cell imaging — «визуализация живых клеток», калька не согласуется
    # Стоп-лист калек и инверсий смысла (разбор 18.10): исправить нельзя — показываем английский термин.
    (r"\w*-?базированн\w*", None),            # «трансформер-базированный» (-based)
    (r"\bчерез\s+воздух\b", None),             # over-the-air
    (r"\bпобег\w*\s+из\s+тюрьм\w*", None),     # jailbreak
    (r"\bнеуникальн\w*", None),                # «физически неуникальные функции» — смысл перевёрнут (unclonable)
    (r"\bстрейн\w*|\bстайфнинг\w*", None),     # «стрейн-стайффнинг»
    (r"\bв\s+поддержке\s+вектор\w*", None),    # «ядра в поддержке векторов» (support vector)
    (r"\bудал[её]нн\w+\s+вычислительн\w+\s+обработк\w*", None),  # «удалённая вычислительная обработка» (over-the-air)
]

# Кальки, которые исправляются только при определённом английском слове в оригинале: «силиконовый» верно для silicone,
# но не для silicon (кремний); «фракционный» верно в химии, но fractional в физике — «дробный».
CONDITIONAL: list[tuple[str, str, str]] = [
    ("silicon", r"\bсиликонов(ый|ая|ое|ые|ого|ой|ых|ым|ую)\b", r"кремниев\1"),
    ("fractional", r"\bфракционн(ый|ая|ое|ые|ого|ой|ых|ым|ую)\b", r"дробн\1"),
    ("moir", r"\bмозаичн(ый|ая|ое|ые|ого|ой|ых|ым|ую)\b", r"муаров\1"),  # moiré — «муаровый», не «мозаичный»
    # all-solid-state — «полностью твердотельный», а не «для всех твердотельных» (смысловая ошибка, прогон 20.10)
    ("all-solid-state", r"\b(для\s+)?вс(?:ех|е|ей)\s+тв[её]рдотельн(\w*)", r"\1полностью твердотельн\2"),
    ("all solid state", r"\b(для\s+)?вс(?:ех|е|ей)\s+тв[её]рдотельн(\w*)", r"\1полностью твердотельн\2"),
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


def check_name_ru(name_en: str, name_ru: str | None, query: str = "") -> tuple[str, str | None]:
    """Русское название для показа и причина, если перевод отвергнут (тогда показывается английский термин).

    Порядок: глоссарий → склейка дефисами → кальки (исправимые исправляются) → проверки валидатора:
    смесь алфавитов в слове, английское слово во множественном числе внутри русской фразы («Обнаружение инъекций prompts»),
    утечка текста запроса в название, слишком длинное название (пересказ вместо термина)."""
    en = (name_en or "").strip()
    key = en.lower()
    if key in GLOSSARY:
        return GLOSSARY[key], None
    if key in KEEP_EN:
        return en, "нет устоявшегося русского термина"
    # GigaChat иногда склеивает слова подчёркиванием («цифровой_двойник_нефтегазовой_отрасли», прогон 20.10).
    ru = re.sub(r"\s+", " ", (name_ru or "").replace("_", " ").strip())
    if not ru:
        return "", None
    if MIXED.search(ru):
        return en, "смесь латиницы и кириллицы в одном слове"
    ru = fix_text_ru(_unglue(ru))
    for pattern, fix in CALQUES:
        if re.search(pattern, ru, flags=re.I):
            if fix is None:
                return en, "известная калька"
            ru = re.sub(pattern, fix, ru, flags=re.I)
    low_en = key.replace("silicone", "")  # silicone (силикон) — не silicon (кремний)
    for word, pattern, fix in CONDITIONAL:
        if word in low_en:
            ru = re.sub(pattern, fix, ru, flags=re.I)
    outside = re.sub(r"\([^)]*\)", " ", ru)  # пояснение в скобках — «вычисления в сенсоре (In-Sensor Computing)» — допустимо
    if CYR.search(outside) and re.search(r"(?<![A-Za-z\-])[a-z]{3,}s\b", outside):
        return en, "английское слово во множественном числе внутри русской фразы"
    q = re.sub(r"\s+", " ", (query or "").lower().strip())
    if len(q) >= 8 and q in ru.lower() and len(ru) > len(q) + 3:
        return en, "в название попал текст запроса"
    n_en = len(re.findall(r"[\w\-]+", en)) or 1
    if len(re.findall(r"[\w\-]+", outside)) > max(7, 3 * n_en):
        return en, "слишком длинное название — пересказ вместо термина"
    return ru, None


# Кальки, которые безопасно исправлять и в свободном тексте справок и резюме (не только в названиях): (шаблон, замена).
TEXT_FIXES: list[tuple[str, object]] = [
    (r"\b([Мм])икрожидкостн", r"\1икрофлюидн"),
    (r"\b([Гг])азового\s+подъ[её]ма\b", r"\1азлифта"),
    (r"\b([Гг])азов\w+\s+подъ[её]м\w*", r"\1азлифт"),
    (r"\b(для\s+)?вс(?:ех|е|ей)\s+тв[её]рдотельн(\w*)", r"\1полностью твердотельн\2"),
    (r"\b3[дД]-", "3D-"),
    # Физика графена (прогон 20.10): «мультислоевом», «тетраслоевого», «моире», «кристаллы винера»
    (r"\b([Мм])ультислое(?:в|йн)", lambda m: ("М" if m.group(1) == "М" else "м") + "ногослойн"),
    (r"\b([Тт])етрасло(?:ев|йн|ен)", lambda m: ("Ч" if m.group(1) == "Т" else "ч") + "етырёхслойн"),
    (r"\b([Фф])ракционн(\w*)(\s+(?:квантов|черновск|изолятор|заряд))", lambda m: ("Д" if m.group(1) == "Ф" else "д") + "робн" + m.group(2) + m.group(3)),
    (r"\b([Мм])оире\b-?", lambda m: ("М" if m.group(1) == "М" else "м") + "уаровые "),
    (r"\bкристалл(\w*)\s+[Вв]инера\b", r"кристалл\1 Вигнера"),
    (r"\bчерновский\s+изолятор(ы|ов|ам|ами|ах)\b", r"черновские изолятор\1"),
    (r"\bна\s+края[хм]\b", "на периферии"),
]


def fix_text_ru(text: str) -> str:
    """Исправление известных калек в тексте справки или резюме источника (без вызова LLM)."""
    if not isinstance(text, str) or not text:
        return text
    for pattern, fix in TEXT_FIXES:
        text = re.sub(pattern, fix, text)
    return text


def normalize_name_ru(name_en: str, name_ru: str | None, query: str = "") -> str:
    """Русское название для показа: глоссарий → исправление калек → английский термин, если перевод неисправим."""
    return check_name_ru(name_en, name_ru, query)[0]


def glossary_hint(limit: int = 18) -> str:
    """Подсказка для промпта GigaChat: принятые переводы терминов."""
    items = list(GLOSSARY.items())[:limit]
    return "; ".join(f"{k} — {v}" for k, v in items)
