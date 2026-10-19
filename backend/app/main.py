import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.collectors.http import prune_cache
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

def startup() -> None:
    init_db()
    s = get_settings()
    removed = prune_cache(Path(s.cache_dir), s.cache_ttl_hours)
    if removed:
        logging.getLogger(__name__).info("cache: removed %d expired files", removed)
    # Запуски, прерванные перезапуском сервера, помечаем как неуспешные, а не «вечно выполняющиеся».
    with SessionLocal() as s:
        for r in s.query(Run).filter(Run.status.in_(["queued", "running"])):
            r.status = "failed"
            r.error = "Обработка прервана перезапуском сервера"
        s.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    startup()
    s = get_settings()
    tasks = []
    if s.precompute_every_hours > 0:
        from app import precompute

        tasks.append(asyncio.create_task(precompute.loop(s.precompute_every_hours)))
    if s.subscriptions_every_hours > 0:  # подписки на темы: пересчёт по расписанию
        from app.pipeline import watch

        tasks.append(asyncio.create_task(watch.loop(s.subscriptions_every_hours)))
    if s.forecast_check_every_hours > 0:  # проверка прогнозов, срок которых наступил
        from app.pipeline import forecasts

        tasks.append(asyncio.create_task(forecasts.loop(s.forecast_check_every_hours)))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Слабые сигналы — API", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


# Режим без Docker/nginx: если рядом собран фронтенд (frontend/dist), backend отдаёт его сам.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        # Только файлы внутри frontend/dist: путь вида /..%2F..%2F.env иначе отдал бы любой файл сервера (в т.ч. ключи).
        f = (_DIST / path).resolve()
        inside = f.is_relative_to(_DIST.resolve())
        return FileResponse(f if path and inside and f.is_file() else _DIST / "index.html")
