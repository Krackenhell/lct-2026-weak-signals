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
    # Версия закреплена: классификатор обучен на ответах jev-1.13.0, а jev-latest может переключиться на новую версию
    # (проверено 19.10: API принимает имя версии и отвечает ею же).
    jev_model: str = "jev-1.13.0"
    kev_base_url: str = "http://127.0.0.1:8009"
    kev_model: str = "kev-latest"

    # LLM для русскоязычных текстов: gigachat | yandexgpt | openai | none
    llm_provider: str = "none"
    gigachat_auth_key: str = ""
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2"
    # Модель для плана поиска (пусто — gigachat_model): шаг из 1–2 вызовов, от которого зависит весь корпус, поэтому
    # более сильная модель здесь окупается. Меняется только по результату A/B (docs/research/AB_МОДЕЛЬ_ПЛАНА.md).
    gigachat_model_plan: str = ""
    gigachat_base_url: str = "https://gigachat.devices.sberbank.ru/api/v1"
    gigachat_auth_url: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    # Проверка TLS: сертификаты Сбера выпущены НУЦ Минцифры, которого нет в стандартном хранилище. Безопасный путь —
    # указать путь к корневому сертификату (GIGACHAT_CA_BUNDLE); false — без проверки (запасной вариант, виден в коде).
    gigachat_verify_ssl: bool = True  # сертификат Минцифры встроен (app/certs/russian_trusted_ca.pem)
    gigachat_ca_bundle: str = ""
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
    # Запасные ключи OpenAlex через запятую: когда дневная квота основного кончается (429), запросы идут по следующему ключу,
    # и только потом — в анонимную квоту. Прогоны не становятся «недействительными» посреди дня.
    openalex_api_key_backup: str = ""
    openalex_email: str = ""
    # Адрес команды для «вежливых» пулов открытых API (Crossref); пусто — используется OPENALEX_EMAIL
    contact_email: str = ""
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
    # Brave Search API: веб- и новостной поиск событий (пилоты, сделки, патенты, закупки) и доводов «против».
    # Бесплатный тариф — 1 запрос/с и 2000 в месяц, поэтому бюджет на прогон и месячный предел.
    brave_api_key: str = ""
    # Источники, подключённые 20.10 (ключи — только в .env): PubMed, NASA ADS, Stack Exchange, Роспатент; без ключа — bioRxiv/medRxiv,
    # ClinicalTrials.gov, SEC EDGAR (обязателен User-Agent с почтой), RSS ЕИС госзакупок.
    ncbi_api_key: str = ""
    nasa_ads_token: str = ""
    stackexchange_key: str = ""
    rospatent_api_key: str = ""
    # SEC EDGAR требует User-Agent «Организация почта»; адреса на mail.ru SEC отклоняет (403, проверено 20.10). Пусто — SEC не запрашивается.
    sec_user_agent: str = ""
    # Lens.org (патенты всего мира с названиями и заявителями): токен — только в .env; 1000 запросов в месяц на пробном тарифе.
    lens_api_token: str = ""
    more_sources: bool = True
    biorxiv_days: int = 7  # свежий каталог bioRxiv/medRxiv: дней (≈100 запросов раз в сутки, в фоне)
    brave_max_calls_per_run: int = 30
    brave_monthly_limit: int = 1900
    # Маршрут источников по профилю запроса (науки о жизни, материалы, энергетика, ИТ): Europe PMC и ML-источники
    routing: bool = True
    http_timeout: float = 25.0
    # Маршрутизация по странам (как раздельный VPN): стенд стоит за рубежом, а часть российских госсайтов отвечает только
    # российским адресам (ЕИС госзакупок нестабилен из-за рубежа). Хосты из RU_PROXY_HOSTS идут через прокси с российским
    # адресом, остальные — напрямую. Если стенд переедет в Россию — наоборот: FOREIGN_PROXY_URL для зарубежных API.
    # Формат прокси: http://логин:пароль@хост:порт или socks5://… При сбое прокси запрос автоматически повторяется напрямую.
    ru_proxy_url: str = ""
    ru_proxy_hosts: str = "zakupki.gov.ru,searchplatform.rospatent.gov.ru,cyberleninka.ru,habr.com,vc.ru,www.cnews.ru"
    foreign_proxy_url: str = ""
    foreign_proxy_hosts: str = "efts.sec.gov,api.search.brave.com,api.lens.org,ops.epo.org,api.typesafe.ai,api.openalex.org"
    cache_dir: Path = DATA_DIR / "cache"
    cache_ttl_hours: int = 72
    # Мягкий дневной лимит сетевых запросов к OpenAlex (по UTC): выше него предрасчёт пропускает темы,
    # чтобы квоту ключа не съели фоновые задачи (бесплатный ключ — около 1000 поисков в сутки).
    openalex_daily_soft_limit: int = 700

    # Живой поиск: аварийный выключатель (false — открываются только готовые результаты) и суточный предел новых расчётов,
    # чтобы квоты Jev, GigaChat и OpenAlex не исчерпал наплыв или чужой скрипт (быстрое исправление 1 из исследования).
    live_search: bool = True
    live_runs_per_day: int = 150
    # Доступ: если задан, запуск поиска и оценки аналитика требуют заголовок X-API-Token (чтение открыто)
    api_token: str = ""

    # Пайплайн
    top_k: int = 15
    # Одновременно обрабатываемых запросов; остальные ждут в очереди (лимиты источников и моделей общие на сервер).
    max_parallel_runs: int = 2
    # Повторный запрос той же темы в течение этого числа часов открывает готовый результат сразу (0 — всегда пересчитывать).
    # 96 часов — на период оценки экспертами (20–23.10); дата расчёта видна на странице, «Пересчитать заново» — всегда.
    reuse_hours: int = 96
    # Предрасчёт тем сервером раз в N часов (0 — выключено); темы через «;», пусто — общий список примеров (app/examples.py).
    precompute_every_hours: float = 0
    precompute_queries: str = ""
    # Подписки на темы: как часто сервер проверяет, не пора ли пересчитать тему (часы, 0 — выключено).
    subscriptions_every_hours: float = 0
    # Прогнозы с проверкой: фиксировать прогноз по сигналам каждого прогона; как часто проверять наступившие (часы, 0 — вручную).
    forecasts_record: bool = True
    forecast_check_every_hours: float = 0
    # Кандидатов на проверку: arXiv требует паузу 3,1 с между запросами, поэтому каждый кандидат — это ~3 с запроса.
    max_candidates: int = 35
    # Бюджет времени на этап проверки кандидатов (секунды, 0 — без лимита): непроверенные к сроку отбрасываются с пометкой.
    # Одиночный прогон укладывается в 60–180 с; лимит защищает от зависшего источника и очереди к общим лимитам.
    run_budget_seconds: int = 300
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

    # Снимки этапов прогона для набора оценки (пусто — не сохранять): data/bench/snapshots
    snapshot_dir: str = ""
    model_dir: Path = DATA_DIR / "model"
    seed_dir: Path = DATA_DIR / "seed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
