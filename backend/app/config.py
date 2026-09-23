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
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt-lite/latest"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4.1"

    # Источники
    openalex_api_key: str = ""
    openalex_email: str = ""
    github_token: str = ""
    http_timeout: float = 25.0
    cache_dir: Path = DATA_DIR / "cache"
    cache_ttl_hours: int = 72

    # Пайплайн
    top_k: int = 15
    max_candidates: int = 50
    confident_threshold: float = 0.75
    use_watchlist: bool = True

    model_dir: Path = DATA_DIR / "model"
    seed_dir: Path = DATA_DIR / "seed"


@lru_cache
def get_settings() -> Settings:
    return Settings()
