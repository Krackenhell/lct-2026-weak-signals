"""REST API для веб-интерфейса."""
import asyncio
import hmac
import json
import math
import os
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
from app.examples import EXAMPLES
from app.llm.providers import llm_label
from app.ml.model import SignalModel
from app.models import Candidate, Document, Feedback, ModelCall, Run
from app.pipeline import runner
from app.pipeline.decide import EXCLUSION_RU, rank_score
from app.pipeline.features import FEATURE_RU
from app.pipeline.passport import card_facts, evidence_checks, why_early
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


def _score(c: Candidate, extra: dict) -> dict | None:
    """Балл места по текущей формуле и для прогонов, сохранённых до неё: min(p; 0,95) × (0,6 + 0,4 × релевантность).
    Точка отсчёта модели для старых прогонов восстанавливается как logit(p) − сумма вкладов."""
    sc = dict(extra.get("score") or {})
    if c.probability is None:
        return sc or None
    rel = c.relevance if c.relevance is not None else sc.get("relevance", 0.0)
    sc.update(probability=round(c.probability, 4), relevance=round(rel, 3), final=round(rank_score(c.probability, rel), 4))
    if sc.get("intercept") is None and extra.get("items"):
        p = min(max(c.probability, 1e-6), 1 - 1e-6)
        sc["intercept"] = round(math.log(p / (1 - p)) - sum(i["contribution"] for i in extra["items"]), 3)
    sc.setdefault("outside_training", [])
    return sc


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
        "score": _score(c, extra),
        "impulse": extra.get("impulse"), "topic_rel": extra.get("topic_rel"),
        # Второе число рядом с оценкой: «Проверки доказательств: k из 5» (счёт проверок, а не вероятность).
        "checks": evidence_checks(extra.get("passport")),
        # П17: «почему рано» — по каким каналам технология уже видна в подтверждённых документах и где её ещё нет.
        "why_early": why_early((extra.get("passport") or {}).get("ladder"),
                               None if "wikipedia" in extra.get("missing", []) else bool((c.features or {}).get("wiki_exists"))),
        "in_training": bool(extra.get("in_training")), "name_check": extra.get("name_check"),
        # Короткие факты для списка: стадия (УГТ), год появления в литературе, рост работ, одна строка описания.
        **card_facts(c.features, c.answers, extra.get("dynamics"), datetime.now(timezone.utc).year, extra.get("missing")),
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


_PREP = {"в", "во", "на", "для", "и", "с", "со", "по", "из", "от", "к", "о", "об", "при", "без", "или", "а", "the", "of", "in", "for", "and", "on"}
_ENDING = re.compile(r"(ами|ями|ого|его|ому|ему|ыми|ими|ах|ях|ов|ев|ей|ий|ый|ой|ая|яя|ое|ее|ые|ие|ых|их|ым|им|ую|юю|ам|ям|а|я|о|е|ы|и|у|ю|ь)$")


def _norm_query(q: str) -> str:
    """Ключ темы: слова без окончаний и предлогов, порядок сохраняется. «Технология многослойного графена» и «технологии
    многослойного графена» — одна тема; «безопасность ИИ» и «ИИ для безопасности», «графен» и «графит» — разные."""
    words = re.findall(r"\w+", q.lower().replace("ё", "е"))
    key = [_ENDING.sub("", w) if len(w) >= 4 and re.search(r"[а-я]", w) else w for w in words if w not in _PREP]
    return " ".join(key) or " ".join(words)


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=timezone.utc) if dt and dt.tzinfo is None else dt  # SQLite не хранит часовой пояс


def reuse_blockers(r: Run) -> list[str]:
    """Почему готовый результат нельзя отдать повторно (пусто — можно). Сломанный прогон не должен отвечать экспертам 4 дня."""
    s = get_settings()
    prov, st = r.providers or {}, r.stats or {}
    out = []
    if prov.get("llm") != _current_llm_label():
        out.append("другая LLM")
    if prov.get("pipeline") != runner.PIPELINE_VERSION:
        out.append("другая версия конвейера")
    if prov.get("decision_model") and not prov["decision_model"].startswith("heuristic") and prov["decision_model"] != _current_decision_label():
        out.append("другая decision-модель")
    if (st.get("decision_fallback") or 0) > 0.2 * max(st.get("candidates") or 0, 1):
        out.append("decision-модель не ответила по части кандидатов")
    if st.get("degraded"):
        out.append("статистика публикаций OpenAlex была недоступна")
    if (r.plan or {}).get("generated_by") == "lexicon" and s.llm_provider.lower() != "none" and _current_llm_label() != "none:template":
        out.append("план поиска построен без LLM")
    if not st.get("signals"):
        out.append("нет сигналов")
    return out


def _current_decision_label() -> str:
    s = get_settings()
    p = s.decision_provider.lower()
    return f"{p}:{s.jev_model if p == 'jev' else s.kev_model if p == 'kev' else 'rules'}"


def _reusable_run(db: Session, query: str, use_watchlist: bool) -> Run | None:
    """Тот же запрос уже выполняется или выполнен недавно той же рабочей конфигурацией — отдаём его сразу.

    Повторный клик жюри не запускает вторую обработку, а готовые темы открываются за секунду, а не за 5 минут.
    Свежесть — REUSE_HOURS; «Пересчитать» в интерфейсе передаёт fresh=true. Не отдаём повторно прогоны другой версии
    конвейера или модели, со сбоем decision-модели или OpenAlex, с планом без LLM (см. reuse_blockers)."""
    hours = get_settings().reuse_hours
    key = _norm_query(query)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    recent = db.query(Run).filter(Run.status.in_(["queued", "running", "done"])).order_by(desc(Run.id)).limit(300).all()
    for r in recent:
        if _norm_query(r.query) != key or bool((r.options or {}).get("use_watchlist", get_settings().use_watchlist)) != use_watchlist:
            continue
        if r.status in ("queued", "running"):
            return r
        fresh_enough = hours > 0 and (_aware(r.created_at) or since) > since
        if fresh_enough and not reuse_blockers(r):
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
    s = get_settings()
    if not s.live_search:
        raise HTTPException(503, "Новые расчёты временно выключены администратором стенда. Готовые результаты по темам с главной открываются.")
    day_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    if s.live_runs_per_day and db.query(Run).filter(Run.created_at >= day_start.replace(tzinfo=None)).count() >= s.live_runs_per_day:
        raise HTTPException(429, "Суточный лимит новых расчётов исчерпан (защита квот моделей и источников). Готовые результаты открываются; "
                                 "новые темы — завтра после 03:00 МСК.")
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
    return llm_label()


@router.get("/examples")
def examples() -> list[str]:
    """Темы для кнопок на главной — тот же список, что рассчитывается заранее: клик открывает готовый ответ."""
    return EXAMPLES


@router.post("/precompute")
async def start_precompute(_: None = Depends(require_token)) -> dict:
    """Предрасчёт тем в том же процессе (общая очередь и общий поток GigaChat): запускать один раз после заморозки кода.
    Требует API_TOKEN, если он задан."""
    from app import precompute

    task = asyncio.create_task(precompute.refresh_once())
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"started": True, "topics": precompute.queries()}


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
        "queue": queue_info(db, run) if run.status == "queued" else None,
        "signals": [_cand_out(c) for c in signals],
        "watch": [_cand_out(c) for c in watch],
        "excluded": [_cand_out(c) for c in excluded],
    }


def queue_info(db: Session, run: Run) -> dict:
    """П15: позиция в очереди и ожидаемое время — по медиане длительности последних 20 завершённых прогонов.
    Одновременно обрабатываются MAX_PARALLEL_RUNS запросов, поэтому ожидание — число «волн» перед запросом."""
    ahead = db.query(Run).filter(Run.status.in_(["queued", "running"]), Run.id < run.id).count()
    recent = db.query(Run).filter(Run.status == "done", Run.finished_at.isnot(None)).order_by(desc(Run.id)).limit(20).all()
    secs = sorted((_aware(r.finished_at) - _aware(r.created_at)).total_seconds() for r in recent if r.created_at)
    median = secs[len(secs) // 2] if secs else 180.0
    par = max(1, get_settings().max_parallel_runs)
    waves = max(0, ahead - par + 1)
    return {"ahead": ahead, "eta_seconds": int(math.ceil(waves / par) * median + median), "median_run_seconds": int(median)}


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
    for key, fname in (("backtest", "backtest.json"), ("timemachine", "timemachine.json"), ("sources_check", "sources_check.json"),
                       ("emergence", "emergence.json"), ("gates_h4", "gates_h4.json"), ("ab_plan_model", "ab_plan_model.json"),
                       ("ab_narrow_plan", "ab_narrow_plan.json"), ("llm_baseline", "llm_baseline.json")):
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
    # Версия кода на стенде: по ней видно, что обновление из GitHub применилось.
    return {"status": "ok", "commit": os.environ.get("APP_COMMIT", "")}


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
