"""REST API для веб-интерфейса."""
import asyncio
import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.ml.model import SignalModel
from app.models import Candidate, Document, ModelCall, Run
from app.pipeline import runner
from app.pipeline.decide import EXCLUSION_RU
from app.pipeline.features import FEATURE_RU
from app.pipeline.questions import QUESTION_RU
from app.pipeline.trust import TRUST_RU, TYPE_RU

router = APIRouter(prefix="/api")
_tasks: set[asyncio.Task] = set()


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    use_watchlist: bool | None = None  # None — по настройке сервера


def _run_out(r: Run) -> dict:
    return {
        "id": r.id, "query": r.query, "status": r.status, "stage": r.stage, "progress": r.progress, "error": r.error,
        "plan": r.plan, "stats": r.stats, "providers": r.providers, "options": r.options or {},
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "finished_at": r.finished_at.isoformat() if r.finished_at else None,
    }


def _doc_out(d: Document) -> dict:
    return {
        "id": d.id, "title": d.title, "url": d.url, "published": d.published, "source_name": d.source_name,
        "source_type": d.source_type, "source_type_ru": TYPE_RU.get(d.source_type, d.source_type),
        "language": d.language, "trust_level": d.trust_level, "trust_level_ru": TRUST_RU.get(d.trust_level, d.trust_level),
        "trust_reason": d.trust_reason, "summary_ru": d.summary_ru, "summary_generated": d.summary_generated, "snippet": d.snippet[:600],
    }


def _cand_out(c: Candidate, brief: bool = True) -> dict:
    items = (c.contributions or {}).get("items", [])
    out = {
        "id": c.id, "run_id": c.run_id, "name": c.name, "name_ru": c.name_ru, "origin": c.origin, "status": c.status, "rank": c.rank,
        "probability": c.probability, "relevance": c.relevance, "exclusion_code": c.exclusion_code,
        "exclusion_label": EXCLUSION_RU.get(c.exclusion_code or "", None), "exclusion_reason": c.exclusion_reason,
        "key_predictors": [i for i in items if i["contribution"] > 0][:3],
        "n_sources": len(c.document_ids or []),
    }
    if not brief:
        out.update(
            features=c.features, contributions=items, methods=(c.contributions or {}).get("methods", []),
            answers={k: {**v, "label": QUESTION_RU.get(k, k)} for k, v in (c.answers or {}).items()}, dossier=c.dossier,
        )
    return out


@router.post("/search")
async def start_search(body: SearchIn, db: Session = Depends(get_session)) -> dict:
    options = {} if body.use_watchlist is None else {"use_watchlist": body.use_watchlist}
    run = Run(query=body.query.strip(), options=options)
    db.add(run)
    db.commit()
    task = asyncio.create_task(runner.execute(run.id))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return _run_out(run)


@router.get("/runs")
def list_runs(db: Session = Depends(get_session)) -> list[dict]:
    return [_run_out(r) for r in db.query(Run).order_by(desc(Run.id)).limit(50)]


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)) -> dict:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Запуск не найден")
    cands = db.query(Candidate).filter_by(run_id=run_id).all()
    signals = sorted([c for c in cands if c.status == "signal"], key=lambda c: c.rank or 999)
    excluded = sorted([c for c in cands if c.status != "signal"], key=lambda c: -(c.probability or 0))
    return {**_run_out(run), "signals": [_cand_out(c) for c in signals], "excluded": [_cand_out(c) for c in excluded]}


@router.get("/candidates/{cand_id}")
def get_candidate(cand_id: int, db: Session = Depends(get_session)) -> dict:
    c = db.get(Candidate, cand_id)
    if not c:
        raise HTTPException(404, "Кандидат не найден")
    docs = [db.get(Document, i) for i in c.document_ids or []]
    run = db.get(Run, c.run_id)
    return {**_cand_out(c, brief=False), "query": run.query if run else "", "sources": [_doc_out(d) for d in docs if d]}


@router.get("/runs/{run_id}/log")
def run_log(run_id: int, db: Session = Depends(get_session)) -> list[dict]:
    calls = db.query(ModelCall).filter_by(run_id=run_id).order_by(ModelCall.id).all()
    return [
        {"id": m.id, "provider": m.provider, "model": m.model, "purpose": m.purpose, "subject": m.subject, "latency_ms": m.latency_ms, "ok": m.ok,
         "request": m.request, "response": m.response, "created_at": m.created_at.isoformat() if m.created_at else None}
        for m in calls
    ]


@router.get("/model")
def model_info() -> dict:
    s = get_settings()
    model = SignalModel.load()
    metrics_path = Path(s.model_dir) / "metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None
    weights = []
    if model:
        weights = sorted(
            [{"feature": f, "label": FEATURE_RU.get(f, f), "weight": round(w, 3)} for f, w in zip(model.features, model.coef)],
            key=lambda r: -abs(r["weight"]),
        )
    return {
        "trained": model is not None, "meta": model.meta if model else None, "weights": weights, "metrics": metrics,
        "providers": {"decision": s.decision_provider, "llm": s.llm_provider},
        "exclusion_codes": EXCLUSION_RU, "confident_threshold": s.confident_threshold,
    }


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}
