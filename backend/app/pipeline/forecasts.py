"""Прогноз с проверкой: честная метрика, которую нельзя подогнать задним числом.

При каждом завершённом прогоне по каждому сигналу фиксируется прогноз «за HORIZON_DAYS дней сигнал усилится» и заранее
записанный критерий. Через срок система сама проверяет его по тем же открытым источникам:
- СБЫЛСЯ, если число научных работ за последние 12 месяцев выросло не меньше чем в GROWTH раза к базе
  ИЛИ технология поднялась на более дальнюю ступень лестницы «от науки до рынка» (патент, раунд, пилот, контракт, закупка);
- НЕ СБЫЛСЯ — иначе; НЕТ ДАННЫХ — если источник недоступен (в долю сбывшихся не входит).
Доля сбывшихся среди проверенных — на странице «Методология». Повторные прогоны той же темы новых прогнозов на ту же
технологию не создают, пока старый не проверен.

Запуск проверки: python -m app.pipeline.forecasts check   (на стенде — по расписанию, см. FORECAST_CHECK_EVERY_HOURS)
"""
import argparse
import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

from app.collectors import brave, openalex
from app.collectors.http import HttpClient, SourceError
from app.db import SessionLocal, init_db
from app.models import Candidate, Forecast, Run
from app.pipeline import market as market_mod

log = logging.getLogger(__name__)

HORIZON_DAYS = 180
GROWTH = 1.5
CRITERIA = (f"Сбылся, если через {HORIZON_DAYS} дней число научных работ за 12 месяцев выросло не меньше чем в {GROWTH:g} раза "
            "к базе на дату прогноза или технология поднялась на более дальнюю ступень лестницы «от науки до рынка».")
ORDER = [k for k, _ in market_mod.STEPS]


async def works_12m(http: HttpClient, phrase: str, at: date) -> int:
    return await openalex.count(http, f"{openalex._phrase_filter(phrase)},from_publication_date:{(at - timedelta(days=365)).isoformat()},"
                                      f"to_publication_date:{at.isoformat()}")


async def record(run_id: int, http: HttpClient | None = None, now: datetime | None = None) -> int:
    """Фиксирует прогнозы по сигналам прогона. Возвращает число новых прогнозов."""
    now = now or datetime.now(timezone.utc)
    own = http is None
    http = http or HttpClient()
    made = 0
    try:
        with SessionLocal() as s:
            run = s.get(Run, run_id)
            if not run or run.status != "done" or (run.options or {}).get("seed_candidates") or (run.options or {}).get("eval"):
                return 0
            sigs = s.query(Candidate).filter_by(run_id=run_id, status="signal").all()
            open_names = {f.name.lower() for f in s.query(Forecast).filter(Forecast.status == "pending")}
            for c in sigs:
                if c.name.lower() in open_names:
                    continue
                try:
                    base = await works_12m(http, c.name, now.date())
                except SourceError:
                    base = None
                reached = (((c.contributions or {}).get("market") or {}).get("ladder") or {}).get("reached")
                s.add(Forecast(run_id=run_id, candidate_id=c.id, query=run.query, name=c.name, made_at=now,
                               check_after=now + timedelta(days=HORIZON_DAYS), probability=c.probability,
                               baseline={"works_12m": base, "reached": reached}, criteria=CRITERIA))
                made += 1
            s.commit()
    finally:
        if own:
            await http.close()
    return made


def _further(a: str | None, b: str | None) -> bool:
    return b is not None and (a is None or ORDER.index(b) > ORDER.index(a))


async def check_due(now: datetime | None = None, http: HttpClient | None = None) -> dict:
    """Проверяет прогнозы, срок которых наступил."""
    now = now or datetime.now(timezone.utc)
    own = http is None
    http = http or HttpClient()
    out = {"checked": 0, "confirmed": 0, "not_confirmed": 0, "unknown": 0}
    try:
        with SessionLocal() as s:
            due = [f for f in s.query(Forecast).filter(Forecast.status == "pending").all()
                   if (f.check_after.replace(tzinfo=timezone.utc) if f.check_after.tzinfo is None else f.check_after) <= now]
            budget = brave.Budget(limit=3 * len(due))
            for f in due:
                base, reached0 = (f.baseline or {}).get("works_12m"), (f.baseline or {}).get("reached")
                try:
                    cur = await works_12m(http, f.name, now.date())
                except SourceError:
                    cur = None
                web = []
                if brave.enabled():
                    for coro in (brave.events(http, f.name, budget), brave.patents(http, f.name, budget)):
                        try:
                            web += await coro
                        except Exception:  # noqa: BLE001
                            pass
                reached = max((market_mod.step_of({"type": d.source_type, "event": d.extra.get("event"), "market": d.extra.get("market"),
                                                   "title": d.title, "snippet": d.snippet}) for d in web), key=lambda k: ORDER.index(k) if k else -1,
                              default=None) if web else None
                growth = (cur / base) if base and cur is not None else None
                if cur is None and not web:
                    status = "unknown"
                elif (growth is not None and growth >= GROWTH) or _further(reached0, reached):
                    status = "confirmed"
                else:
                    status = "not_confirmed"
                f.status, f.checked_at = status, now
                f.result = {"works_12m": cur, "growth": round(growth, 2) if growth else None, "reached": reached,
                            "new_step": _further(reached0, reached), "evidence": [d.url for d in web[:5]]}
                out["checked"] += 1
                out[status] += 1
            s.commit()
    finally:
        if own:
            await http.close()
    return out


def summary() -> dict:
    with SessionLocal() as s:
        fs = s.query(Forecast).all()
    checked = [f for f in fs if f.status in ("confirmed", "not_confirmed")]
    nxt = min((f.check_after for f in fs if f.status == "pending"), default=None)
    return {"total": len(fs), "pending": sum(f.status == "pending" for f in fs), "checked": len(checked),
            "confirmed": sum(f.status == "confirmed" for f in checked),
            "confirmed_share": round(sum(f.status == "confirmed" for f in checked) / len(checked), 3) if checked else None,
            "next_check": nxt.isoformat() if nxt else None, "criteria": CRITERIA}


async def loop(every_hours: float) -> None:
    while True:
        try:
            log.info("forecasts: %s", await check_due())
        except Exception:  # noqa: BLE001 — проверка прогнозов не должна останавливать сервер
            log.exception("forecast check failed")
        await asyncio.sleep(every_hours * 3600)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["check", "summary"])
    args = ap.parse_args()
    init_db()
    print(asyncio.run(check_due()) if args.cmd == "check" else summary())


if __name__ == "__main__":
    main()
