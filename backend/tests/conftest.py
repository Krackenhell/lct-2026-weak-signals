"""Общая обвязка тестов: изолированная БД и кэш, без сети и без ключей моделей.

Переменные окружения выставляются ДО импорта приложения: движок БД создаётся при импорте app.db,
а настройки кэшируются. Переменные окружения имеют приоритет над файлом .env, поэтому локальные
ключи разработчика на тесты не влияют.
"""
import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="weak-signals-tests-"))
os.environ["DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["CACHE_DIR"] = str(_TMP / "cache")
os.environ["DECISION_PROVIDER"] = "heuristic"
os.environ["LLM_PROVIDER"] = "none"
os.environ["TYPESAFE_API_KEY"] = ""
os.environ["GIGACHAT_AUTH_KEY"] = ""
os.environ["OPENALEX_API_KEY"] = ""
os.environ["OPENALEX_EMAIL"] = ""
os.environ["GITHUB_TOKEN"] = ""
os.environ["S2_API_KEY"] = ""
os.environ["API_TOKEN"] = ""
os.environ["CHECK_LINKS"] = "false"  # живая проверка ссылок ходит в сеть; в тестах она подменяется (test_links.py)

import pytest  # noqa: E402

from app.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.db import init_db  # noqa: E402

init_db()


@pytest.fixture(autouse=True)
def _fresh_robots():
    """Правила robots.txt кэшируются на процесс; в тестах у каждого своя поддельная сеть."""
    from app.collectors import news_search, robots, yc

    robots._RULES.clear()
    yc._DATA = None  # каталог YC тоже кэшируется на процесс
    news_search._PARSED.clear()  # и разобранные ленты
    yield


@pytest.fixture
def tmp_dir() -> Path:
    return _TMP
