import logging

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.db import SessionLocal, init_db
from app.models import Run

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logging.getLogger("httpx").setLevel(logging.WARNING)

app = FastAPI(title="Слабые сигналы — API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
app.include_router(router)


@app.on_event("startup")
def startup() -> None:
    init_db()
    # Запуски, прерванные перезапуском сервера, помечаем как неуспешные, а не «вечно выполняющиеся».
    with SessionLocal() as s:
        for r in s.query(Run).filter(Run.status.in_(["queued", "running"])):
            r.status = "failed"
            r.error = "Обработка прервана перезапуском сервера"
        s.commit()


# Режим без Docker/nginx: если рядом собран фронтенд (frontend/dist), backend отдаёт его сам.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = _DIST / path
        return FileResponse(f if path and f.is_file() else _DIST / "index.html")
