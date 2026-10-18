"""Предрасчёт тем: чтобы ключевые запросы открывались сразу, а не через 5–6 минут.

Сервер сам пересчитывает темы раз в PRECOMPUTE_EVERY_HOURS (0 — выключено) по очереди, через ту же очередь
запусков, что и запросы пользователей: один слот занят предрасчётом, второй свободен для живого запроса.
Тема пропускается, если по ней уже есть свежий результат (REUSE_HOURS).

Разовый запуск вручную: python -m app.precompute [--queries "q1;q2"]
"""
import argparse
import asyncio
import logging

from app.api.routes import _reusable_run
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Run
from app.pipeline import runner

log = logging.getLogger(__name__)

# 6 областей датасета организатора — те же формулировки, что в живой оценке (app/ml/eval_live.py).
DEFAULT_QUERIES = [
    "перспективные решения в финтехе",
    "слабые сигналы в кибербезопасности ИИ",
    "робототехника",
    "edge AI и вычисления на устройствах",
    "инфраструктура для ИИ",
    "индустриальный ИИ",
]


def queries() -> list[str]:
    raw = get_settings().precompute_queries
    return [q.strip() for q in raw.split(";") if q.strip()] if raw else DEFAULT_QUERIES


async def refresh_once(topics: list[str] | None = None) -> list[int]:
    """Пересчитывает темы без свежего результата; возвращает номера новых запусков."""
    s = get_settings()
    started = []
    for q in topics or queries():
        with SessionLocal() as db:
            if _reusable_run(db, q, s.use_watchlist):
                continue
            run = Run(query=q, options={"precompute": True})
            db.add(run)
            db.commit()
            run_id = run.id
        log.info("precompute: %s (run %s)", q, run_id)
        await runner.execute(run_id)
        started.append(run_id)
    return started


async def loop(every_hours: float) -> None:
    while True:
        try:
            await refresh_once()
        except Exception:  # предрасчёт не должен останавливать сервер
            log.exception("precompute failed")
        await asyncio.sleep(every_hours * 3600)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="", help="темы через «;» (по умолчанию — 6 областей датасета)")
    args = ap.parse_args()
    init_db()
    topics = [q.strip() for q in args.queries.split(";") if q.strip()] or None
    print("Запуски:", asyncio.run(refresh_once(topics)))


if __name__ == "__main__":
    main()
