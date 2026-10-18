from collections.abc import Iterator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


_settings = get_settings()
_connect_args = {"check_same_thread": False} if _settings.database_url.startswith("sqlite") else {}
engine = create_engine(_settings.database_url, pool_pre_ping=True, connect_args=_connect_args)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    from app import models  # noqa: F401  регистрирует таблицы

    Base.metadata.create_all(engine)
    # Новые столбцы в уже существующих таблицах (стенд с данными прошлых прогонов): create_all их не добавляет.
    cols = {c["name"] for c in inspect(engine).get_columns("documents")}
    if "link_status" not in cols:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE documents ADD COLUMN link_status VARCHAR(20)"))


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session
