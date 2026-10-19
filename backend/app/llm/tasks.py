"""Задачи для LLM с жёсткой привязкой к найденным документам, и шаблонные запасные варианты."""
import asyncio
import hashlib
import json
import re
import time
from pathlib import Path

from app.llm.providers import BaseLLM, LLMResult, parse_json
from app.llm.terms import glossary_hint, normalize_name_ru

# Лимиты на короткие шаги, у которых есть запасные правила: если GigaChat «завис» (замер: до 4 минут при сбое
# сервиса — 3 попытки по 120 с), аналитик не ждёт, а запрос идёт дальше по правилам.
CHECK_DEADLINE = 30.0
PLAN_DEADLINE = 45.0


async def _within(llm: BaseLLM, coro, seconds: float) -> LLMResult:
    t = time.perf_counter()
    try:
        return await asyncio.wait_for(coro, seconds)
    except asyncio.TimeoutError:
        return LLMResult("", llm.provider, llm.model, int((time.perf_counter() - t) * 1000), ok=False, error=f"нет ответа за {seconds:.0f} с")

# Направления банка для радара (тот же список, что в pipeline/passport.py — там же правила без LLM).
BANK_AREA_NAMES = [
    "Платежи и переводы", "Цифровые активы и токенизация", "Кредитование и скоринг", "Антифрод и ПОД/ФТ", "Комплаенс и KYC",
    "Кибербезопасность", "ИТ-инфраструктура и данные", "Клиентский сервис и каналы", "Инвестиции и казначейство", "Вне ключевых направлений банка",
]

SYSTEM_ANALYST = (
    "Ты — технологический аналитик банка. Работаешь ТОЛЬКО с предоставленными документами. "
    "Не добавляй фактов, которых нет в документах. Отвечай строго в запрошенном JSON-формате."
)

# Правило для русских названий: без машинных калек вроде «AI-настороженный ядро банковского дела».
NAME_RU_RULE = (
    "название на русском так, как его написал бы отраслевой аналитик или русскоязычное IT-издание; "
    "грамматически согласованное; если устоявшегося русского термина нет — оставь английский термин или аббревиатуру "
    "(например «direct air capture», «федеративное обучение», «оркестрация инференса на периферии»); "
    "слова пиши через пробел, не склеивай дефисами; принятые переводы: " + glossary_hint()
)

# Словарь для расширения ШИРОКОГО запроса без LLM: направления -> англоязычные поисковые темы.
# «Чип» — только чипы для ИИ: голое «чип» отправляло «микрофлюидные чипы» и «органы на чипе» в дата-центры ИИ.
DOMAIN_LEXICON = {
    r"финтех|финанс|банк|платеж|платёж|fintech|payment|bank": ["fintech", "digital payments", "tokenization banking", "AI agents payments", "stablecoin", "credit scoring", "anti-money laundering", "digital identity verification", "decentralized finance", "regtech compliance"],
    r"кибер|безопасн|защит|security|cyber": ["AI security", "LLM security", "prompt injection", "agent security", "post-quantum cryptography", "confidential computing", "model supply chain security", "deepfake detection", "zero trust AI"],
    r"робот|robot": ["robot learning", "humanoid robot", "robot manipulation", "vision-language-action", "legged robot", "soft robotics", "robot foundation model", "swarm robotics", "teleoperation"],
    r"edge|периферийн|iot|интернет вещей|устройств": ["edge AI", "on-device LLM", "TinyML", "neuromorphic", "in-sensor computing", "edge inference accelerator", "federated learning edge", "NPU"],
    r"инфраструктур|дата-центр|цод|ии-чип|чип\w* для ии|ai chip|полупровод|hardware|infrastructure|datacenter|gpu": ["AI accelerator", "AI data center", "optical interconnect", "photonic computing", "memory disaggregation CXL", "KV cache", "inference optimization", "chiplet", "in-memory computing"],
    r"индустр|промышлен|производств|завод|industrial|manufactur": ["industrial AI", "AI manufacturing", "industrial foundation model", "predictive quality", "AI process control", "industrial agents", "generative design", "robotic welding"],
    r"\bии\b|искусственн|нейросет|машинн|\bai\b|artificial intelligence|llm|генератив": ["large language model", "AI agents", "multimodal model", "small language model", "reasoning model", "model compression", "AI evaluation", "agentic workflow"],
    r"энерг|energy|батар|аккумул|накопит": ["energy storage", "virtual power plant", "solid-state battery", "grid AI", "small modular reactor", "hydrogen electrolysis", "sodium-ion battery"],
    r"медиц|здрав|health|биотех|biotech|фарм": ["AI drug discovery", "digital pathology", "medical foundation model", "gene editing", "wearable diagnostics", "microrobots medicine"],
    r"квант|quantum": ["quantum error correction", "quantum sensing", "post-quantum cryptography", "quantum networking", "quantum-inspired algorithms"],
    r"космос|спутник|space|satellite": ["satellite edge computing", "orbital data center", "direct-to-device satellite", "space robotics", "in-orbit servicing"],
    r"транспорт|авто|логист|transport|mobility|logistic": ["autonomous trucking", "vehicle-to-grid", "drone logistics", "AI logistics optimization", "event camera automotive"],
    r"ритейл|торгов|retail|e-commerce|commerce": ["agentic commerce", "AI shopping agent", "retail computer vision", "dynamic pricing AI"],
    r"материал|material|химия|chemistry": ["AI materials discovery", "self-driving laboratory", "metamaterials", "self-healing materials"],
    r"агро|сельск|agri|food": ["precision agriculture AI", "agricultural robotics", "vertical farming", "alternative protein"],
}


# Проверка запроса без LLM: технологические корни слов и явные признаки «не технологического» запроса.
TECH_HINTS = (
    r"технолог|инновац|алгоритм|вычисл|сенсор|датчик|материал|сет[ьи]\b|данн|модел|платформ|протокол|микро|нано|"
    r"генн|геном|крипт|токен|агент|автоном|дрон|беспилот|спутник|чип|процессор|облак|цифров|кибер|нейро|"
    r"оптик|фотон|лазер|батаре|водород|реактор|синтез|печат|3d|vr|ar\b|метавселен|интерфейс|автоматиз|"
    r"анализ|прогноз|распозна|зрени|речев|язык.*модел|решени[яй]|тренд|сигнал|направлени"
)
NON_TECH = r"привет|здравств|добрый (день|вечер)|как дела|спасибо|пока\b|анекдот|погод|кто такой|почему .*(лучш|худш)|лучший вуз|^тест$|^\W*$"


def rule_check_query(query: str) -> dict:
    """Прозрачное правило: запрос принимается, если похож на технологическое направление."""
    q = query.lower().strip()
    lexicon_hit = any(re.search(p, q) for p in DOMAIN_LEXICON) or re.search(TECH_HINTS, q)
    latin_term = re.search(r"[a-z][a-z0-9\-]{2,}", q)  # «edge AI», «TinyML» и т.п.
    letters = re.findall(r"[a-zа-яё]", q)
    # Мусор и код вместо запроса: повтор одной буквы, только цифры и знаки, SQL или HTML без технологической темы.
    garbage = len(set(letters)) < 4 or re.search(r"\b(select|drop|insert|delete|union)\b.*\b(from|table|into)\b|<\s*/?\s*(script|img|iframe)|javascript:", q)
    if garbage and not lexicon_hit:
        return {"ok": False, "reason": "Запрос не похож на технологическое направление (нет осмысленных слов).", "by": "rules"}
    if re.search(NON_TECH, q) and not lexicon_hit:
        return {"ok": False, "reason": "Запрос не похож на технологическое направление (приветствие, бытовой или оценочный вопрос).", "by": "rules"}
    if len(re.findall(r"\w", q)) < 3:
        return {"ok": False, "reason": "Слишком короткий запрос — укажите технологическое направление.", "by": "rules"}
    if lexicon_hit or latin_term:
        return {"ok": True, "reason": "Запрос относится к технологическому направлению (словарь направлений).", "by": "rules"}
    # Неизвестное слово (например, «микрофлюидика») не отклоняем: без LLM лучше проверить, чем отказать.
    return {"ok": True, "reason": "Направление не найдено в словаре — проверяется по источникам.", "by": "rules", "uncertain": True}


async def check_query(llm: BaseLLM, query: str) -> tuple[dict, LLMResult | None]:
    """Шаг 0: это вообще технологическое направление? GigaChat отвечает с причиной; без LLM — правила."""
    if llm.provider == "none":
        return rule_check_query(query), None
    prompt = (
        f"Запрос пользователя в сервис поиска ранних технологических трендов: «{query}».\n"
        "Определи, является ли запрос технологическим, научным или отраслевым направлением, по которому можно искать "
        "новые технологии (например «финтех», «кибербезопасность ИИ», «микрофлюидика», «edge AI»). "
        "Приветствия, бытовые вопросы, оценки организаций и людей, бессмысленный текст — не являются. "
        'Верни JSON: {"is_tech": true или false, "reason": "одно предложение на русском"}.'
    )
    res = await _within(llm, llm.complete(SYSTEM_ANALYST, prompt, temperature=0.0, max_tokens=200), CHECK_DEADLINE)
    data = parse_json(res.text) if res.ok else None
    if isinstance(data, dict) and isinstance(data.get("is_tech"), bool):
        rules = rule_check_query(query)
        ok = data["is_tech"]
        # Страховка от ошибки модели: явное приветствие отклоняем даже при ответе «да».
        if ok and not rules["ok"] and not rules.get("uncertain"):
            ok = False
        return {"ok": ok, "reason": str(data.get("reason") or "").strip() or rules["reason"], "by": f"{res.provider}:{res.model}"}, res
    return rule_check_query(query), res


def clean_phrase(s: str) -> str:
    """Поисковая фраза без склеек: «smart_wellhead_monitoring», «oil-and-gas-technology» → слова через пробел."""
    s = re.sub(r"[_\-–—/]+", " ", str(s or ""))
    return re.sub(r"\s+", " ", re.sub(r"[\"«»“”]", "", s)).strip()


# Слова, которые не задают предмет запроса: «перспективные решения», «слабые сигналы», «новые технологии».
FILLER = re.compile(
    r"^(перспективн|решени|слаб|сигнал|технолог|нов|направлени|тренд|развити|област|сфер|современн|инновац|вычисл|"
    r"emerging|new|novel|technolog|solution|trend|signal|weak|promising)", re.I)
STOPWORDS = {"в", "во", "на", "для", "и", "с", "со", "по", "из", "от", "к", "о", "об", "при", "без", "или", "а", "the", "of", "in",
             "for", "and", "on", "to", "a", "an", "дело", "отрасль", "отрасли"}


def content_words(query: str) -> list[str]:
    """Содержательные слова запроса: без предлогов и слов-наполнителей."""
    return [w for w in re.findall(r"[a-zа-яё0-9][a-zа-яё0-9\-]*", query.lower().replace("ё", "е"))
            if w not in STOPWORDS and len(w) >= 2 and not FILLER.match(w)]


def is_broad(query: str) -> bool:
    """Широкий запрос — каждое содержательное слово относится к направлению из словаря («финтех», «кибербезопасность ИИ»,
    «энергетика и накопители»). Узкий — есть слово вне словаря («микрофлюидные чипы», «многослойный графен», «газлифт»).
    Правило детерминированное и объяснимое: флаг от LLM нестабилен. Для узкого запроса подтемы словаря не подмешиваются —
    иначе «чип» уводил «микрофлюидные чипы» в дата-центры ИИ, а «устройства» — в edge AI."""
    words = content_words(query)
    return bool(words) and all(any(re.search(p, w) for p in DOMAIN_LEXICON) for w in words)


# Корни слов для перевода узкого запроса без LLM (когда GigaChat не ответил за PLAN_DEADLINE или не настроен).
# Порядок слов в русской и английской фразе совпадает («многослойный графен» → «multilayer graphene»).
ROOTS_RU_EN: list[tuple[str, str]] = [
    # Предлоги уже убраны (content_words): «органы на чипе» здесь — «органы чипе».
    (r"орган\w* чип", "organ-on-a-chip"), (r"лаборатори\w* чип", "lab-on-a-chip"), (r"термоядерн\w* синтез", "nuclear fusion"),
    (r"многослойн", "multilayer"), (r"двухслойн|бислойн", "bilayer"), (r"графен", "graphene"), (r"графит", "graphite"),
    (r"микрофлюид", "microfluidic"), (r"перовскит", "perovskite"), (r"солнечн", "solar"), (r"элемент", "cell"),
    (r"твердотельн", "solid-state"), (r"аккумулятор|батаре", "battery"), (r"натрий-ионн", "sodium-ion"), (r"литий-ионн", "lithium-ion"),
    (r"биопечат", "bioprinting"), (r"нейроморфн", "neuromorphic"), (r"чип", "chip"), (r"квантов", "quantum"), (r"сенсор|датчик", "sensor"),
    (r"спинтроник", "spintronics"), (r"биосенсор", "biosensor"), (r"термоядерн", "fusion"), (r"синтез", "synthesis"),
    (r"мрнк", "mRNA"), (r"вакцин", "vaccine"), (r"противоопухолев", "cancer"), (r"персонализированн", "personalized"),
    (r"нейроинтерфейс", "brain-computer interface"), (r"беспилотн", "autonomous"), (r"грузовик", "truck"), (r"мембран", "membrane"),
    (r"опреснени", "desalination"), (r"гибк", "flexible"), (r"устройств", "device"), (r"газлифт", "gas lift"), (r"скважин", "well"),
    (r"нефтегаз", "oil and gas"), (r"нефт", "oil"), (r"водород", "hydrogen"), (r"электролиз", "electrolysis"), (r"топливн", "fuel"), (r"катализ|катализатор", "catalyst"),
    (r"полимер", "polymer"), (r"композит", "composite"), (r"метаматериал", "metamaterial"), (r"наноч|наночастиц", "nanoparticle"),
    (r"постквантов", "post-quantum"), (r"криптограф", "cryptography"), (r"шифровани", "encryption"), (r"гомоморфн", "homomorphic"),
    (r"агентн", "agentic"), (r"платеж|платёж", "payments"), (r"диагностик", "diagnostics"), (r"crispr", "CRISPR"),
    (r"редактировани\w* генов|генн\w* редактир", "gene editing"), (r"спайков|импульсн\w* нейр", "spiking neural network"),
    (r"оптическ", "optical"), (r"фотонн", "photonic"), (r"лазер", "laser"), (r"сверхпровод", "superconducting"), (r"магнит", "magnetic"),
]


def translate_roots(query: str) -> str:
    """Перевод узкого запроса по корням, только если переведено каждое содержательное слово (иначе — пустая строка:
    наполовину переведённая фраза в точном поиске хуже, чем перевод через Википедию)."""
    rest = " ".join(content_words(query))
    out: list[str] = []
    while rest.strip():
        best = None
        for pat, en in ROOTS_RU_EN:
            m = re.match(r"\s*(" + pat + r")[а-яёa-z\-]*", rest)
            if m and (best is None or m.end() > best[0]):
                best = (m.end(), en)
        if not best:
            return ""
        out.append(best[1])
        rest = rest[best[0]:]
    return " ".join(dict.fromkeys(out))


def _latin(phrases) -> list[str]:
    """Только англоязычные поисковые фразы: кириллица в arXiv и OpenAlex ищет точную русскую фразу и находит 0 работ."""
    return [p for p in phrases if p and not re.search(r"[а-яё]", p, re.I)]


def fallback_plan(query: str) -> dict:
    q = query.lower()
    latin = [t.strip() for t in re.findall(r"[a-zA-Z][a-zA-Z0-9\- ]{2,}", query) if t.strip()]
    if not is_broad(query):
        # Узкий запрос: сам предмет по-английски (корни слов), без подтем словаря. Если корней не хватило,
        # английский термин найдёт шаг «растущие поднаправления» через межъязыковые ссылки Википедии.
        en = latin or [t for t in [translate_roots(query)] if t]
        if en:
            return {"topic_en": en[0], "query_en": en[:3], "subqueries": en[:3], "ru_terms": [query], "generated_by": "lexicon", "broad": False}
        # Перевести не удалось: последний запасной вариант — подтемы словаря для слов запроса, которые в нём есть
        # («квантовые сенсоры для медицины» → quantum sensing, …). Помечены backup: как только шаг «растущие
        # поднаправления» найдёт английский термин в литературе, эти подтемы отбрасываются.
        topics = [t for p, terms in DOMAIN_LEXICON.items() if re.search(p, q) for t in terms]
        return {"topic_en": query, "query_en": [], "subqueries": list(dict.fromkeys(topics))[:10], "ru_terms": [query],
                "generated_by": "lexicon", "broad": False, "backup": bool(topics)}
    topics: list[str] = []
    for pattern, terms in DOMAIN_LEXICON.items():
        if re.search(pattern, q):
            topics += [t for t in terms if t not in topics]
    topics = latin + topics
    seen: set[str] = set()
    topics = [t for t in topics if not (t.lower() in seen or seen.add(t.lower()))]  # без повторов («edge AI» из запроса и словаря)
    if not topics:
        topics = [query]
    return {"topic_en": topics[0], "subqueries": topics[:10], "ru_terms": [query], "generated_by": "lexicon", "broad": True}


def _narrow_order(subs: list[str], query_en: list[str]) -> list[str]:
    """Сначала подзапросы, которые делят слово с самим запросом: точный поиск и вопрос о релевантности совпадают с запросом."""
    words = {w for q in query_en for w in re.findall(r"[a-z0-9]{3,}", q.lower())}
    return sorted(subs, key=lambda s: not (words & set(re.findall(r"[a-z0-9]{3,}", s.lower()))))


PLAN_CACHE_DAYS = 14


def plan_prompt(query: str) -> str:
    # Примеры в промпте — нейтральные, не из датасета организатора и не из примеров экспертов.
    return (
        f"Запрос аналитика: «{query}».\n"
        "Сформируй план поиска РАННИХ технологических сигналов (новые технические подходы последних 1-2 лет) в научных и отраслевых источниках. "
        "Не включай зрелые общие темы вроде «AI in banking», «blockchain», «biometrics», «machine learning». "
        "Верни JSON: {\"query_en\": 1-3 устоявшихся английских названия самого предмета запроса (как в заголовках научных статей), "
        "\"topic_en\": краткое название области на английском, "
        "\"subqueries\": 10 англоязычных поисковых фраз по 2-4 слова, каждая — узкое новое направление внутри области "
        "(например для энергетики: «agrivoltaics», «direct air capture sorbents»; для переработки пластика: «enzymatic PET recycling»), "
        "\"ru_terms\": 3 русскоязычные поисковые фразы так, как их пишут в российских научных статьях и на Хабре, "
        "\"zh_terms\": 3 короткие китайские поисковые фразы (упрощённые иероглифы) так, как их пишут китайские техно-СМИ}. "
        "Не называй конкретные компании."
    )


def plan_cache_key(llm: BaseLLM, query: str) -> str:
    """Ключ кэша плана: модель, системная роль и сам промпт. Смена промпта или модели — новый план."""
    return hashlib.sha1(f"{llm.provider}:{llm.model}|{SYSTEM_ANALYST}|{plan_prompt(query)}".encode()).hexdigest()


async def plan_query(llm: BaseLLM, query: str, cache_dir: Path | None = None, refresh: bool = False) -> tuple[dict, LLMResult | None]:
    """План поиска. П12: температура 0 и кэш сырого ответа на PLAN_CACHE_DAYS дней — повторный запрос той же темы идёт по
    тому же плану, поэтому «Пересчитать» и мониторинг темы сравнивают выдачу, а не случайные подтемы. Кэшируется только
    успешный план от LLM; сброс — опция прогона replan."""
    prompt = plan_prompt(query)
    path = cache_dir / f"{plan_cache_key(llm, query)}.json" if cache_dir else None
    res = None
    if path and not refresh and path.exists() and time.time() - path.stat().st_mtime < PLAN_CACHE_DAYS * 86400:
        try:
            cached = json.loads(path.read_text(encoding="utf-8"))
            res = LLMResult(cached["text"], llm.provider, llm.model, 0, usage={})
        except (OSError, ValueError, KeyError):
            res = None
    from_cache = res is not None
    if res is None:
        res = await _within(llm, llm.complete(SYSTEM_ANALYST, prompt, temperature=0.0, max_tokens=700), PLAN_DEADLINE)
    data = parse_json(res.text) if res.ok else None
    if path and not from_cache and isinstance(data, dict) and data.get("subqueries"):
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"text": res.text, "query": query, "model": f"{llm.provider}:{llm.model}"}, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    if isinstance(data, dict) and data.get("subqueries"):
        base = fallback_plan(query)
        broad = base["broad"]
        # GigaChat иногда склеивает слова дефисом («synthetic-data credit-scoring») или подчёркиванием
        # («smart_wellhead_monitoring», замечено на запросе «нефтегазовое дело») — точный поиск по фразе в arXiv
        # и OpenAlex такое не находит. Склейку заменяем пробелом (термины вроде «zero-knowledge» поиск по словам находит).
        raw = data["subqueries"] if isinstance(data["subqueries"], list) else []
        subs = _latin(p for p in (clean_phrase(s) for s in raw if isinstance(s, str)) if p and len(p.split()) <= 6)
        q_en = data.get("query_en")
        q_en = _latin(clean_phrase(t) for t in (q_en if isinstance(q_en, list) else [q_en]) if isinstance(t, str))[:3]
        data["ru_terms"] = [clean_phrase(t) for t in data.get("ru_terms", []) if isinstance(t, str) and clean_phrase(t)]
        topic = clean_phrase(str(data.get("topic_en") or ""))
        data["topic_en"] = topic if topic and not re.search(r"[а-яё]", topic, re.I) else base["topic_en"]
        data["broad"] = broad
        if broad:
            # Широкий запрос: половина подтем — от LLM (новые узкие направления), половина — из проверенного словаря области.
            subs = subs[:6]
            data["subqueries"] = subs + [t for t in base["subqueries"] if t not in subs][: max(0, 12 - len(subs))]
        else:
            # Узкий запрос: сам предмет по-английски первым, затем подтемы LLM; словарь не подмешивается.
            q_en = q_en or base.get("query_en") or []
            subs = _narrow_order([s for s in subs if s.lower() not in {q.lower() for q in q_en}], q_en)
            data["query_en"] = q_en
            data["subqueries"] = (q_en + subs)[:12]
            if q_en:
                data["topic_en"] = q_en[0]
        # Китайские фразы: только строки с иероглифами (модель иногда возвращает пиньинь или английский).
        data["zh_terms"] = [t.strip() for t in data.get("zh_terms", []) if isinstance(t, str) and re.search(r"[一-鿿]", t)][:3]
        data["generated_by"] = f"{res.provider}:{res.model}"
        data["plan_cached"] = from_cache
        return data, (None if from_cache else res)
    return fallback_plan(query), res if llm.provider != "none" else None


async def extract_candidates(llm: BaseLLM, topic: str, docs: list[dict]) -> tuple[list[dict], LLMResult]:
    """Извлекает названия конкретных технологий из пачки документов (со ссылками на номера документов)."""
    listing = "\n".join(f"[{i}] {d['title']}. {d.get('snippet', '')[:260]}" for i, d in enumerate(docs))
    prompt = (
        f"Область: {topic}.\nДокументы:\n{listing}\n\n"
        "Выдели КОНКРЕТНЫЕ технологии или технические подходы, которые обсуждаются в документах "
        "(например «agrivoltaics», «enzymatic PET recycling», «direct air capture sorbents»), а не общие области "
        "(не «AI», не «blockchain», не «robotics»), не компании и не продукты. Объединяй синонимы. "
        "Название — короткий термин класса технологий, каким его написали бы в заголовке отраслевой новости, а НЕ заголовок статьи: "
        "не «Characterization of …», не «… Model of …», не «… under stress», без хвостов «development», «applications», «technologies». "
        "Выделяй только технологии, относящиеся к области; соседние темы из других областей пропускай. "
        "Верни JSON-массив до 15 объектов: {\"name_en\": 2-6 слов на английском, \"name_ru\": " + NAME_RU_RULE + ", "
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
            raw = c.get("docs")
            # Модель иногда пишет "docs": null, 3 или "1, 4" — это не должно ронять запрос.
            raw = raw if isinstance(raw, list) else re.findall(r"\d+", str(raw)) if raw is not None else []
            ids = sorted({int(i) for i in raw if isinstance(i, int) or (isinstance(i, str) and i.isdigit())} & set(range(len(docs))))
            name_en = str(c["name_en"]).strip()
            out.append({"name_en": name_en, "name_ru": normalize_name_ru(name_en, str(c.get("name_ru") or "")), "doc_idx": ids})
    return out, res


def _salvage_candidates(text: str) -> list[dict]:
    """Разбор «почти JSON», который иногда возвращают LLM: достаём поля регулярными выражениями."""
    out = []
    pattern = r'name_en\W+([^"\n]+?)\s*"\s*,\s*"?\s*name_ru\W+([^"\n]*?)\s*"(.*?)(?=name_en|\Z)'
    for m in re.finditer(pattern, text or "", flags=re.S):
        docs = [int(x) for x in re.findall(r"\d+", (re.search(r"docs\W*\[([^\]]*)\]", m.group(3)) or [None, ""])[1])]
        out.append({"name_en": m.group(1).strip(), "name_ru": m.group(2).strip(), "docs": docs})
    return out


async def write_dossier(llm: BaseLLM, query: str, name: str, evidence: list[dict], facts: list[str]) -> tuple[dict | None, LLMResult]:
    listing = "\n".join(
        f"[{i + 1}] ({e['type']}, {e['source']}, {e.get('date') or 'без даты'}) {e['title']}. {e.get('snippet', '')[:500]}" for i, e in enumerate(evidence)
    )
    prompt = (
        f"Запрос аналитика: «{query}». Технология: «{name}».\n"
        "Наблюдаемые показатели (используй как есть, не пересчитывай):\n- " + "\n- ".join(facts) + "\n"
        f"Документы:\n{listing}\n\n"
        "Подготовь аналитическую справку на русском языке ТОЛЬКО по этим документам, со ссылками вида [n] на номера документов. "
        "Не используй кавычки-цитаты, если не приводишь текст документа дословно. "
        "Верни JSON: {\"name_ru\": " + NAME_RU_RULE + ", "
        "\"description\": что это за технология (2-3 предложения), "
        "\"advantage\": потенциальное преимущество (1-2 предложения), "
        "\"case_example\": конкретный пример применения или пилота, описанный в документах, с указанием организации [n]; "
        "не придумывай организации и события — если конкретного примера в документах нет, напиши «В найденных документах описаны только исследовательские прототипы» и укажи [n], "
        "\"application\": где и кем технология может применяться — отрасли и типы задач (1-2 предложения, только по документам), "
        "\"why_weak_signal\": почему это ранний сигнал, а не зрелый тренд (2-3 предложения с опорой на показатели и документы), "
        "\"risks\": что может помешать развитию (1 предложение)}."
    )
    res = await llm.complete(SYSTEM_ANALYST, prompt, temperature=0.2, max_tokens=1400)
    data = parse_json(res.text) if res.ok else None
    if not isinstance(data, dict):
        return None, res
    # Поля досье — только строки: список или вложенный объект от модели сломал бы проверку утверждений.
    flat = lambda v: v if isinstance(v, str) else " ".join(map(str, v)) if isinstance(v, list) else "" if v is None else str(v)  # noqa: E731
    return {k: flat(v) for k, v in data.items()}, res


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
