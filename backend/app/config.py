"""Настройки приложения. Все значения читаются из переменных окружения / файла .env."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BACKEND_DIR / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(BACKEND_DIR.parent / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # База данных. В Docker — PostgreSQL, для локальной разработки допускается SQLite.
    database_url: str = f"sqlite:///{(DATA_DIR / 'local.db').as_posix()}"

    # Decision-модель (System One API): jev | kev | heuristic
    decision_provider: str = "heuristic"
    typesafe_api_key: str = ""
    typesafe_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-latest"
    kev_base_url: str = "http://127.0.0.1:8009"
    kev_model: str = "kev-latest"

    # LLM для русскоязычных текстов: gigachat | yandexgpt | openai | none
    llm_provider: str = "none"
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2"
    gigachat_verify_ssl: bool = False
    # Параллельных запросов к GigaChat: 1 — бесплатный тариф физлица; для корпоративного тарифа можно 4–8,
    # тогда 15 досье пишутся одновременно, а не по очереди.
    gigachat_concurrency: int = 1
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt-lite/latest"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1"

    # Экономика запроса. Пусто — ориентировочный тариф провайдера из app/pipeline/cost.py; локальные модели — 0.
    llm_rub_per_1k_tokens: float | None = None
    decision_rub_per_call: float = 0.0  # Jev: по договору с TypeSafe (на хакатоне — без оплаты); Kev локально — 0

    # Источники
    openalex_api_key: str = ""
    openalex_email: str = ""
    github_token: str = ""
    s2_api_key: str = ""  # Semantic Scholar: без ключа источник не используется (лимит 429)
    # Дополнительные научные источники и языки: Crossref (все издатели), КиберЛенинка (RU), Europe PMC (науки о жизни),
    # новости на китайском (GDELT). Выключаются, если нужна максимальная скорость.
    extra_sources: bool = True
    # Отраслевые новости и раунды инвестиций: RSS-ленты изданий (EN/RU) и поиск SiliconANGLE, с проверкой robots.txt
    news_sources: bool = True
    # Госгранты NIH, NSF, UKRI: доказательства по кандидатам и проекты по подтемам в корпусе
    grant_sources: bool = True
    # Стартапы Y Combinator (открытый каталог): доказательства по кандидатам и стартапы по подтемам в корпусе
    startup_sources: bool = True
    # Ранние исследования в ИИ: Hugging Face Papers и OpenReview (для запросов про ИИ, роботов, вычисления, данные)
    ml_sources: bool = True
    # Патенты (в т.ч. Китай) через EPO OPS: бесплатный ключ на developers.epo.org; без ключа источник выключен
    epo_ops_key: str = ""
    epo_ops_secret: str = ""
    http_timeout: float = 25.0
    cache_dir: Path = DATA_DIR / "cache"
    cache_ttl_hours: int = 72

    # Доступ: если задан, запуск поиска и оценки аналитика требуют заголовок X-API-Token (чтение открыто)
    api_token: str = ""

    # Пайплайн
    top_k: int = 15
    # Одновременно обрабатываемых запросов; остальные ждут в очереди (лимиты источников и моделей общие на сервер).
    max_parallel_runs: int = 2
    # Повторный запрос той же темы в течение этого числа часов открывает готовый результат сразу (0 — всегда пересчитывать).
    reuse_hours: int = 24
    # Предрасчёт тем сервером раз в N часов (0 — выключено); темы через «;», пусто — 6 областей датасета.
    precompute_every_hours: float = 0
    precompute_queries: str = ""
    # Кандидатов на проверку: arXiv требует паузу 3,1 с между запросами, поэтому каждый кандидат — это ~3 с запроса.
    max_candidates: int = 30
    # Новости GDELT по каждому кандидату: лимит 1 запрос / 5,5 с и частые отказы делали этот шаг самым долгим.
    # По умолчанию новости собираются в корпусе и для окна для России.
    news_per_candidate: bool = False
    # Живая проверка ссылок источников в итоговой выдаче
    check_links: bool = True
    confident_threshold: float = 0.75
    # База отслеживания подмешивает сигналы датасета в кандидаты — по умолчанию выключена (чистое обнаружение).
    use_watchlist: bool = False
    # Паспорт доказательств: сколько документов должна подтвердить decision-модель, чтобы кандидат попал в топ.
    min_confirmed_docs: int = 3
    # Окно для России: сверка с русскоязычными источниками для сигналов топа.
    russia_window: bool = True

    model_dir: Path = DATA_DIR / "model"
    seed_dir: Path = DATA_DIR / "seed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
