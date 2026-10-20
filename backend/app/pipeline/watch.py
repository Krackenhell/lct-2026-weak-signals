"""Подписка на тему: сервер пересчитывает тему раз в every_days дней и записывает, что изменилось.

«Изменилось» — по фактам, а не по формулировкам: новый сигнал в топе, выпавший сигнал и УСИЛИВШИЙСЯ сигнал — тот, что
поднялся по лестнице «от науки до рынка» (появился патент, раунд, пилот, контракт, закупка) или по паспорту доказательств
(C → B → A). Сводка видна на странице «Подписки»; если указан webhook — отправляется туда JSON-ом (адрес задаёт пользователь).

Включение на сервере: SUBSCRIPTIONS_EVERY_HOURS > 0 (проверка, не пора ли пересчитать). Вручную: python -m app.pipeline.watch
"""
import argparse
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.db import SessionLocal, init_db
from app.models import Candidate, Run, Subscription, SubscriptionEvent
from app.pipeline import market as market_mod
from app.pipeline import runner

log = logging.getLogger(__name__)
ORDER = [k for k, _ in market_mod.STEPS]
LEVEL = {"C": 0, "B": 1, "A": 2}


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _state(c: Candidate) -> dict:
    ex = c.contributions or {}
    return {"name": c.name, "name_ru": c.name_ru, "level": (ex.get("passport") or {}).get("level"),
            "reached": ((ex.get("market") or {}).get("ladder") or {}).get("reached")}


def compare(session, prev_id: int | None, new_id: int) -> dict:
    """Что изменилось между двумя прогонами одной темы."""
    new = {_key(c.name): _state(c) for c in session.query(Candidate).filter_by(run_id=new_id, status="signal")}
    old = {_key(c.name): _state(c) for c in session.query(Candidate).filter_by(run_id=prev_id, status="signal")} if prev_id else {}
    stronger = []
    for k, n in new.items():
        o = old.get(k)
        if not o:
            continue
        why = []
        if n["reached"] and (o["reached"] is None or ORDER.index(n["reached"]) > ORDER.index(o["reached"])):
            why.append(f"новая ступень: {market_mod.LABEL[n['reached']]}")
        if LEVEL.get(n["level"] or "C", 0) > LEVEL.get(o["level"] or "C", 0):
            why.append(f"доказательства {o['level']} → {n['level']}")
        if why:
            stronger.append({**n, "why": why})
    return {"new": [new[k] for k in new if k not in old] if old else [], "dropped": [old[k] for k in old if k not in new],
            "stronger": stronger, "first": not old}


def summarize(diff: dict) -> str:
    if diff["first"]:
        return "Первый расчёт темы по подписке."
    parts = []
    if diff["stronger"]:
        parts.append("усилились: " + "; ".join(f"{s['name_ru'] or s['name']} ({', '.join(s['why'])})" for s in diff["stronger"][:5]))
    if diff["new"]:
        parts.append("новые: " + ", ".join(s["name_ru"] or s["name"] for s in diff["new"][:5]))
    if diff["dropped"]:
        parts.append("выпали: " + ", ".join(s["name_ru"] or s["name"] for s in diff["dropped"][:5]))
    return ("; ".join(parts) + ".").capitalize() if parts else "Существенных изменений нет."


async def refresh(sub_id: int, now: datetime | None = None) -> SubscriptionEvent | None:
    """Пересчитывает тему подписки и записывает изменения."""
    now = now or datetime.now(timezone.utc)
    with SessionLocal() as s:
        sub = s.get(Subscription, sub_id)
        if not sub or not sub.active:
            return None
        run = Run(query=sub.query, options={"subscription": sub.id})
        s.add(run)
        s.commit()
        run_id, prev_id = run.id, sub.last_run_id
    await runner.execute(run_id)
    with SessionLocal() as s:
        sub = s.get(Subscription, sub_id)
        run = s.get(Run, run_id)
        if run.status != "done":
            sub.next_at = now + timedelta(hours=6)  # сбой — повтор через 6 часов, прошлый расчёт остаётся базой
            s.commit()
            return None
        diff = compare(s, prev_id, run_id)
        ev = SubscriptionEvent(subscription_id=sub.id, run_id=run_id, prev_run_id=prev_id, summary=summarize(diff), payload=diff)
        s.add(ev)
        sub.last_run_id, sub.next_at = run_id, now + timedelta(days=sub.every_days)
        s.commit()
        s.refresh(ev)
        hook, payload = sub.webhook, {"query": sub.query, "run_id": run_id, "summary": ev.summary, **diff}
    if hook and not diff["first"]:
        try:
            from app.pipeline.links import _guard, resolves_internal

            if await resolves_internal(hook):
                raise ValueError("адрес webhook указывает во внутреннюю сеть")
            # Каждый запрос, включая переадресации, проверяется на внутренний адрес (защита от обращений во внутреннюю сеть).
            async with httpx.AsyncClient(timeout=15, event_hooks={"request": [_guard]}) as client:
                await client.post(hook, json=payload)
        except Exception as exc:  # noqa: BLE001 — недоступный webhook не ломает подписку
            log.warning("subscription %s webhook failed: %s", sub_id, exc)
    return ev


async def run_due(now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    with SessionLocal() as s:
        due = [x.id for x in s.query(Subscription).filter(Subscription.active.is_(True)).all()
               if (x.next_at.replace(tzinfo=timezone.utc) if x.next_at.tzinfo is None else x.next_at) <= now]
    done = []
    for sid in due:
        if await refresh(sid, now):
            done.append(sid)
    return done


async def loop(every_hours: float) -> None:
    while True:
        try:
            await run_due()
        except Exception:  # noqa: BLE001 — подписки не должны останавливать сервер
            log.exception("subscriptions failed")
        await asyncio.sleep(every_hours * 3600)


def main() -> None:
    argparse.ArgumentParser().parse_args()
    init_db()
    print("Пересчитаны подписки:", asyncio.run(run_due()))


if __name__ == "__main__":
    main()
