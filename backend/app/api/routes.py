"""REST API для веб-интерфейса."""
import asyncio
import hmac
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy import desc, func
from sqlalchemy.orm import Session

from app import export as export_mod
from app.config import get_settings
from app.db import get_session
from app.ml.model import SignalModel
from app.models import Candidate, Document, Feedback, ModelCall, Run
from app.pipeline import runner
from app.pipeline.decide import EXCLUSION_RU
from app.pipeline.features import FEATURE_RU
from app.pipeline.passport import card_facts
from app.pipeline.questions import QUESTION_RU
from app.pipeline.trust import TRUST_RU, TYPE_RU

router = APIRouter(prefix="/api")
_tasks: set[asyncio.Task] = set()


def require_token(x_api_token: str | None = Header(default=None), token: str | None = None) -> None:
    """Если задан API_TOKEN, изменяющие запросы (запуск поиска, оценки аналитика) требуют токен.
    Чтение результатов остаётся открытым — жюри и аналитики смотрят выдачу без настройки."""
    expected = get_settings().api_token
    if expected and not hmac.compare_digest((x_api_token or token or "").encode(), expected.encode()):
        raise HTTPException(401, "Нужен токен доступа (заголовок X-API-Token)")


class SearchIn(BaseModel):
    query: str = Field(min_length=2, max_length=300)
    use_watchlist: bool | None = None  # None — по настройке сервера
    fresh: bool = False  # True — пересчитать, даже если свежий результат по этой теме уже есть


def _run_out(r: Run) -> dict:
    return {
        "id": r.id, "query": r.query, "status": r.status, "stage": r.stage, "progress": r.progress, "error": r.error,
        "plan": r.plan, "stats": r.stats, "providers": r.providers, "options": r.options or {},
        "created_at": _aware(r.created_at).isoformat() if r.created_at else None,
        "finished_at": _aware(r.finished_at).isoformat() if r.finished_at else None,  # с часовым поясом, как created_at
    }


def _doc_out(d: Document) -> dict:
    return {
        "id": d.id, "title": d.title, "url": d.url, "published": d.published, "source_name": d.source_name,
        "source_type": d.source_type, "source_type_ru": TYPE_RU.get(d.source_type, d.source_type),
        "language": d.language, "trust_level": d.trust_level, "trust_level_ru": TRUST_RU.get(d.trust_level, d.trust_level),
        "trust_reason": d.trust_reason, "summary_ru": d.summary_ru, "summary_generated": d.summary_generated, "snippet": d.snippet[:600],
        "link_status": d.link_status,
    }


def _first_sentence(text: str, limit: int = 220) -> str:
    """Первое предложение описания без ссылок [n] — строка под названием в списке сигналов."""
    if "выявленная в документах по запросу" in (text or ""):
        return ""  # шаблонное описание (LLM не вернула своё) — в списке не показываем
    s = re.sub(r"\s*\[\d+(?:[,\s]+\d+)*\]", "", text or "").strip()
    m = re.match(r"(.+?[.!?])(\s|$)", s)
    s = m.group(1) if m else s
    return s if len(s) <= limit else s[: limit - 1].rsplit(" ", 1)[0] + "…"


def _cand_out(c: Candidate, brief: bool = True) -> dict:
    extra = c.contributions or {}
    items = extra.get("items", [])
    out = {
        "id": c.id, "run_id": c.run_id, "name": c.name, "name_ru": c.name_ru, "origin": c.origin, "status": c.status, "rank": c.rank,
        "probability": c.probability, "relevance": c.relevance, "exclusion_code": c.exclusion_code,
        "exclusion_label": EXCLUSION_RU.get(c.exclusion_code or "", None), "exclusion_reason": c.exclusion_reason,
        "key_predictors": [i for i in items if i["contribution"] > 0][:3],
        "n_sources": len(c.document_ids or []),
        # Проверяемость вывода (новое): паспорт доказательств, запас прочности, окно для России.
        "passport": extra.get("passport"), "robustness": extra.get("robustness"), "window": extra.get("window"),
        "radar": extra.get("radar"), "dynamics": extra.get("dynamics"), "missing": extra.get("missing", []),
        "geography": extra.get("geography"), "startups_by_year": extra.get("startups_by_year"), "patents": extra.get("patents"),
        "score": extra.get("score"),
        # Короткие факты для списка: стадия (УГТ), год появления в литературе, рост работ, одна строка описания.
        **card_facts(c.features, c.answers, extra.get("dynamics"), datetime.now(timezone.utc).year),
        "summary": _first_sentence((c.dossier or {}).get("description", "")) if (c.dossier or {}).get("generated_by") not in (None, "template") else "",
    }
    if not brief:
        fb = sorted(c.feedback, key=lambda f: f.id)[-1] if getattr(c, "feedback", None) else None
        out["feedback"] = {"verdict": fb.verdict, "label": VERDICTS.get(fb.verdict, fb.verdict), "comment": fb.comment} if fb else None
        out.update(
            features=c.features, contributions=items, methods=(c.contributions or {}).get("methods", []),
            answers={k: {**v, "label": QUESTION_RU.get(k, k)} for k, v in (c.answers or {}).items()}, dossier=c.dossier,
        )
    return out


def _norm_query(q: str) -> str:
    return " ".join(re.findall(r"\w+", q.lower().replace("ё", "е")))


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt  # SQLite не хранит часовой пояс


def _reusable_run(db: Session, query: str, use_watchlist: bool) -> Run | None:
    """Тот же запрос уже выполняется или выполнен недавно той же рабочей моделью — отдаём его сразу.

    Повторный клик жюри не запускает вторую обработку, а готовые темы открываются за секунду, а не за 5 минут.
    Свежесть — REUSE_HOURS (по умолчанию сутки); «Пересчитать» в интерфейсе передаёт fresh=true."""
    hours = get_settings().reuse_hours
    key = _norm_query(query)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    llm = _current_llm_label()
    recent = db.query(Run).filter(Run.status.in_(["queued", "running", "done"])).order_by(desc(Run.id)).limit(300).all()
    for r in recent:
        if _norm_query(r.query) != key or bool((r.options or {}).get("use_watchlist", get_settings().use_watchlist)) != use_watchlist:
            continue
        if r.status in ("queued", "running"):
            return r
        fresh_enough = hours > 0 and (_aware(r.created_at) or since) > since
        if fresh_enough and (r.providers or {}).get("llm") == llm and (r.stats or {}).get("signals"):
            return r
    return None


@router.post("/search")
async def start_search(body: SearchIn, db: Session = Depends(get_session), _: None = Depends(require_token)) -> dict:
    options ={} if body.use_watchlist is None else {"use_watchlist": body.use_watchlist}
    if not body.fresh:
        watch = get_settings().use_watchlist if body.use_watchlist is None else body.use_watchlist
        prev = _reusable_run(db, body.query, watch)
        if prev:
            return {**_run_out(prev), "reused": True}
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


@router.get("/showcase")
def showcase(db: Session = Depends(get_session)) -> list[dict]:
    """Готовые прогоны: последний завершённый запуск по каждой теме — открываются мгновенно (для показа и мониторинга)."""
    seen, out = set(), []
    done = db.query(Run).filter(Run.status == "done").order_by(desc(Run.id)).limit(200).all()
    # Прогоны на запасных правилах (без decision-модели) показываем, только если других нет.
    real = [r for r in done if not (r.providers or {}).get("decision_model", "").startswith("heuristic")]
    # По каждой теме — сначала прогон текущей рабочей модели из настроек (пробные прогоны другими моделями
    # остаются в истории запросов, но не подменяют рабочий результат на главной).
    current = _current_llm_label()
    ordered = sorted(real or done, key=lambda r: ((r.providers or {}).get("llm") != current, -r.id))
    for r in ordered:
        key = r.query.strip().lower()
        if key in seen or not (r.stats or {}).get("signals"):
            continue
        seen.add(key)
        out.append({
            "run_id": r.id, "query": r.query, "date": _aware(r.created_at).isoformat() if r.created_at else None,
            "signals": r.stats.get("signals"), "passport": r.stats.get("passport"), "providers": r.providers,
            "mode": "мониторинг" if (r.options or {}).get("use_watchlist") else "обнаружение",
            "seconds": int((r.finished_at - r.created_at).total_seconds()) if r.finished_at and r.created_at else None,
        })
        if len(out) >= 12:
            break
    return sorted(out, key=lambda x: -x["run_id"])


def _current_llm_label() -> str:
    """Подпись рабочей LLM в том же виде, что пишет прогон в providers.llm (без подключения к модели)."""
    s = get_settings()
    p = s.llm_provider.lower()
    if p == "gigachat" and s.gigachat_auth_key:
        return f"gigachat:{s.gigachat_model}"
    if p == "yandexgpt" and s.yandex_api_key:
        return f"yandexgpt:{s.yandex_model}"
    if p == "openai" and s.openai_api_key:
        return f"openai:{s.openai_model}"
    return "none:template"


@router.get("/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_session)) -> dict:
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Запуск не найден")
    cands = db.query(Candidate).filter_by(run_id=run_id).all()
    signals = sorted([c for c in cands if c.status == "signal"], key=lambda c: c.rank or 999)
    watch = sorted([c for c in cands if c.status == "watch"], key=lambda c: -(c.probability or 0))
    excluded = sorted([c for c in cands if c.status not in ("signal", "watch")], key=lambda c: -(c.probability or 0))
    return {
        **_run_out(run),
        "signals": [_cand_out(c) for c in signals],
        "watch": [_cand_out(c) for c in watch],
        "excluded": [_cand_out(c) for c in excluded],
    }


VERDICTS = {"signal": "Слабый сигнал", "mature": "Зрелая технология", "noise": "Завышенные ожидания без подтверждений", "not_tech": "Не технология"}


class FeedbackIn(BaseModel):
    verdict: str = Field(pattern="^(signal|mature|noise|not_tech)$")
    comment: str = Field(default="", max_length=2000)


@router.post("/candidates/{cand_id}/feedback")
def add_feedback(cand_id: int, body: FeedbackIn, db: Session = Depends(get_session), _: None = Depends(require_token)) -> dict:
    """Решение аналитика: сохраняется со снимком признаков и используется при дообучении (python -m app.ml.train --refit --with-feedback)."""
    c = db.get(Candidate, cand_id)
    if not c:
        raise HTTPException(404, "Кандидат не найден")
    run = db.get(Run, c.run_id)
    fb = Feedback(candidate_id=c.id, run_id=c.run_id, verdict=body.verdict, comment=body.comment.strip(), name=c.name, features=c.features or {},
                  provider=(run.providers or {}).get("decision_model", "") if run else "", n_docs=len(c.document_ids or []))
    db.add(fb)
    db.commit()
    return {"id": fb.id, "verdict": fb.verdict, "label": VERDICTS[fb.verdict]}


@router.get("/feedback/stats")
def feedback_stats(db: Session = Depends(get_session)) -> dict:
    rows = db.query(Feedback).all()
    by = {k: 0 for k in VERDICTS}
    for f in rows:
        by[f.verdict] = by.get(f.verdict, 0) + 1
    # Согласие аналитика с системой: оценка «слабый сигнал» для кандидата из топа и любая другая — для исключённого.
    agree = 0
    judged = 0
    for f in rows:
        c = db.get(Candidate, f.candidate_id)
        if c:
            judged += 1
            agree += (c.status == "signal") == (f.verdict == "signal")
    return {"total": len(rows), "by_verdict": by, "labels": VERDICTS, "agreement": round(agree / judged, 3) if judged else None}


@router.get("/runs/{run_id}/export")
def export_run(run_id: int, format: str = "xlsx", db: Session = Depends(get_session)) -> Response:
    """Выгрузка результата: xlsx (колонки датасета организатора + листы «Наблюдать», «Исключённые», «Источники»), csv, json, md."""
    if format not in export_mod.FORMATS:
        raise HTTPException(400, f"Формат: {', '.join(export_mod.FORMATS)}")
    run = db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Запуск не найден")
    data = export_mod.build(run, db.query(Candidate).filter_by(run_id=run_id).all(), db.query(Document).filter_by(run_id=run_id).all())
    fn, mime = export_mod.FORMATS[format]
    name = f"weak-signals-run-{run_id}.{format}"
    return Response(fn(data), media_type=mime, headers={"Content-Disposition": f'attachment; filename="{name}"'})


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
    live_path = Path(s.model_dir) / "live_eval.json"
    live = json.loads(live_path.read_text(encoding="utf-8")) if live_path.exists() else None
    comp_path = Path(s.model_dir) / "decision_model_comparison.json"
    comparison = json.loads(comp_path.read_text(encoding="utf-8")) if comp_path.exists() else None
    extra = {}
    for key, fname in (("backtest", "backtest.json"), ("timemachine", "timemachine.json"), ("sources_check", "sources_check.json")):
        p = Path(s.model_dir) / fname
        extra[key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else None
    weights = []
    if model:
        weights = sorted(
            [{"feature": f, "label": FEATURE_RU.get(f, f), "weight": round(w, 3)} for f, w in zip(model.features, model.coef, strict=False)],
            key=lambda r: -abs(r["weight"]),
        )
    return {
        "trained": model is not None, "meta": model.meta if model else None, "weights": weights, "metrics": metrics,
        "live_eval": live, "decision_comparison": comparison, **extra,
        "providers": {"decision": s.decision_provider, "llm": s.llm_provider},
        "exclusion_codes": EXCLUSION_RU, "confident_threshold": s.confident_threshold,
    }


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.get("/metrics", response_class=PlainTextResponse)
def metrics(db: Session = Depends(get_session)) -> str:
    """Метрики в формате Prometheus: запуски, кандидаты, вызовы моделей и их задержка, сбои источников, оценки аналитиков."""
    out = []

    def gauge(name: str, help_: str, rows: list[tuple[dict, float]]) -> None:
        out.append(f"# HELP {name} {help_}")
        out.append(f"# TYPE {name} gauge")
        for labels, value in rows:
            lab = ",".join(f'{k}="{v}"' for k, v in labels.items())
            out.append(f"{name}{{{lab}}} {value}" if lab else f"{name} {value}")

    gauge("weak_signals_runs", "Запуски по статусу", [({"status": s}, n) for s, n in db.query(Run.status, func.count()).group_by(Run.status)])
    gauge("weak_signals_candidates", "Кандидаты по решению", [({"status": s}, n) for s, n in db.query(Candidate.status, func.count()).group_by(Candidate.status)])
    calls = db.query(ModelCall.provider, ModelCall.ok, func.count(), func.avg(ModelCall.latency_ms)).group_by(ModelCall.provider, ModelCall.ok).all()
    gauge("weak_signals_model_calls", "Вызовы моделей", [({"provider": p, "ok": str(bool(ok)).lower()}, n) for p, ok, n, _ in calls])
    gauge("weak_signals_model_latency_ms_avg", "Средняя задержка вызова модели, мс", [({"provider": p, "ok": str(bool(ok)).lower()}, round(lat or 0, 1)) for p, ok, _, lat in calls])
    done = db.query(Run).filter(Run.status == "done", Run.finished_at.isnot(None)).order_by(desc(Run.id)).limit(50).all()
    secs = [(r.finished_at - r.created_at).total_seconds() for r in done if r.created_at]
    gauge("weak_signals_run_seconds_avg", "Среднее время обработки запроса (последние 50), с", [({}, round(sum(secs) / len(secs), 1) if secs else 0)])
    costs = [(r.stats or {}).get("cost", {}).get("total_rub") for r in done]
    costs = [c for c in costs if c is not None]
    gauge("weak_signals_run_cost_rub_avg", "Средняя стоимость запроса (последние 50), руб.", [({}, round(sum(costs) / len(costs), 2) if costs else 0)])
    gauge("weak_signals_runs_in_progress", "Запросы в очереди и в работе", [({}, db.query(Run).filter(Run.status.in_(["queued", "running"])).count())])
    fails: dict[str, list[int]] = {}
    for r in db.query(Run).filter(Run.status == "done").order_by(desc(Run.id)).limit(20):
        for host, st in ((r.stats or {}).get("http") or {}).items():
            agg = fails.setdefault(host, [0, 0])
            agg[0] += st.get("failed", 0)
            agg[1] += st.get("ok", 0) + st.get("cached", 0) + st.get("failed", 0)
    gauge("weak_signals_source_failure_ratio", "Доля неудачных запросов к источнику (последние 20 прогонов)", [({"host": h}, round(f / t, 3) if t else 0) for h, (f, t) in sorted(fails.items())])
    gauge("weak_signals_feedback", "Оценки аналитиков", [({"verdict": v}, n) for v, n in db.query(Feedback.verdict, func.count()).group_by(Feedback.verdict)])
    return "\n".join(out) + "\n"
