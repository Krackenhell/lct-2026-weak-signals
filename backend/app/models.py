"""Схема хранения: запуск запроса, собранные документы, кандидаты, журнал вызовов моделей."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Run(Base):
    """Один запуск открытого запроса пользователя."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    query: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued|running|done|failed
    stage: Mapped[str] = mapped_column(String(200), default="")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    plan: Mapped[dict] = mapped_column(JSON, default=dict)  # расширение запроса: подтемы, термины
    stats: Mapped[dict] = mapped_column(JSON, default=dict)
    providers: Mapped[dict] = mapped_column(JSON, default=dict)
    options: Mapped[dict] = mapped_column(JSON, default=dict)  # параметры запуска (например, use_watchlist)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    candidates: Mapped[list["Candidate"]] = relationship(back_populates="run", cascade="all, delete-orphan")
    documents: Mapped[list["Document"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class Document(Base):
    """Источник (статья, препринт, новость, репозиторий...) с метаданными для проверки."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(1000))
    title: Mapped[str] = mapped_column(Text)
    snippet: Mapped[str] = mapped_column(Text, default="")
    published: Mapped[str | None] = mapped_column(String(10), nullable=True)  # ISO-дата YYYY-MM-DD
    source_name: Mapped[str] = mapped_column(String(200))  # arXiv, OpenAlex/журнал, домен СМИ...
    source_type: Mapped[str] = mapped_column(String(50))  # science|preprint|news|repository|community|reference|patent
    language: Mapped[str] = mapped_column(String(10), default="en")
    trust_level: Mapped[str] = mapped_column(String(20))  # high|medium|low
    trust_reason: Mapped[str] = mapped_column(String(300), default="")
    collector: Mapped[str] = mapped_column(String(50))
    summary_ru: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    link_status: Mapped[str | None] = mapped_column(String(20), nullable=True)  # ok|dead|restricted — живая проверка ссылки

    run: Mapped[Run] = relationship(back_populates="documents")


class Candidate(Base):
    """Кандидат в слабые сигналы (технология) и решение по нему."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(300))
    name_ru: Mapped[str | None] = mapped_column(String(300), nullable=True)
    origin: Mapped[str] = mapped_column(String(20), default="discovered")  # discovered|watchlist
    status: Mapped[str] = mapped_column(String(20), default="candidate")  # signal|excluded|candidate
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probability: Mapped[float | None] = mapped_column(Float, nullable=True)
    relevance: Mapped[float | None] = mapped_column(Float, nullable=True)
    exclusion_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    features: Mapped[dict] = mapped_column(JSON, default=dict)
    contributions: Mapped[dict] = mapped_column(JSON, default=dict)
    answers: Mapped[dict] = mapped_column(JSON, default=dict)
    dossier: Mapped[dict] = mapped_column(JSON, default=dict)
    document_ids: Mapped[list] = mapped_column(JSON, default=list)

    run: Mapped[Run] = relationship(back_populates="candidates")
    feedback: Mapped[list["Feedback"]] = relationship(cascade="all, delete-orphan")


class Feedback(Base):
    """Решение аналитика по кандидату (human-in-the-loop): используется для дообучения классификатора."""

    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"), index=True)
    run_id: Mapped[int] = mapped_column(Integer, index=True)
    verdict: Mapped[str] = mapped_column(String(20))  # signal|mature|noise|not_tech
    comment: Mapped[str] = mapped_column(Text, default="")
    name: Mapped[str] = mapped_column(String(300), default="")
    features: Mapped[dict] = mapped_column(JSON, default=dict)  # снимок признаков на момент оценки
    provider: Mapped[str] = mapped_column(String(100), default="")  # decision-модель, давшая признаки
    n_docs: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ModelCall(Base):
    """Журнал каждого обращения к модели: какая модель, зачем, что ответила."""

    __tablename__ = "model_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True, nullable=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(300), default="")
    request: Mapped[dict] = mapped_column(JSON, default=dict)
    response: Mapped[dict] = mapped_column(JSON, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
