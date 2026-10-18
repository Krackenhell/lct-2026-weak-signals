"""Живая оценка на открытых запросах (этап 2 ТЗ).

Для 6 областей датасета считаем, сколько сигналов организатора попало в топ-15:
- с базой отслеживания (как работает сервис);
- без неё — чистое обнаружение из открытых источников (честная полнота).
Для тем вне датасета фиксируем выдачу для ручной экспертной проверки.

Запуск: python -m app.ml.eval_live [--only-discovery] [--queries "q1;q2"]
Результат: data/model/live_eval.json
"""
import argparse
import asyncio
import json
import re
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Candidate, Run
from app.pipeline import runner

DOMAIN_QUERIES = {
    "Финтех": "перспективные решения в финтехе",
    "Защита ИИ": "слабые сигналы в кибербезопасности ИИ",
    "Роботы": "робототехника",
    "Edge": "edge AI и вычисления на устройствах",
    "Инфраструктура ИИ": "инфраструктура для ИИ",
    "Индустриальный ИИ": "индустриальный ИИ",
}
EXTRA_QUERIES = ["энергетика и накопители энергии", "медицинские технологии"]
# Контроль: на такие запросы система должна отказать, а не выдать список «сигналов».
NONSENSE_QUERIES = ["Привет", "почему мирэа лучший вуз"]


def _words(s: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]{3,}", s.lower())}


def matches(cand_name: str, terms: list[str]) -> bool:
    cw = _words(cand_name)
    for t in terms:
        tw = _words(t)
        if tw and len(cw & tw) / len(tw | cw) >= 0.5:
            return True
    return False


async def run_query(query: str, use_watchlist: bool) -> int:
    with SessionLocal() as s:
        run = Run(query=query, options={"use_watchlist": use_watchlist, "eval": True})
        s.add(run)
        s.commit()
        run_id = run.id
    await runner.execute(run_id)
    return run_id


def summarize(run_id: int, domain: str | None) -> dict:
    s_ = get_settings()
    seed = Path(s_.seed_dir)
    items = json.loads((seed / "weak_signals_2026.json").read_text(encoding="utf-8"))
    terms = json.loads((seed / "positive_terms.json").read_text(encoding="utf-8"))
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        cands = s.query(Candidate).filter_by(run_id=run_id).all()
        signals = sorted([c for c in cands if c.status == "signal"], key=lambda c: c.rank or 99)
        out = {
            "run_id": run_id, "query": run.query, "status": run.status, "options": run.options,
            "seconds": int((run.finished_at - run.created_at).total_seconds()) if run.finished_at else None,
            "n_signals": len(signals), "confident_75": sum(1 for c in signals if (c.probability or 0) >= 0.75),
            "new_candidates_in_top": sum(1 for c in signals if c.origin == "discovered"),
            "top": [
                {"rank": c.rank, "name": c.name, "name_ru": c.name_ru, "p": round(c.probability or 0, 3), "origin": c.origin,
                 "passport": ((c.contributions or {}).get("passport") or {}).get("level"),
                 "window": ((c.contributions or {}).get("window") or {}).get("status")}
                for c in signals
            ],
            "passport": {lv: sum(1 for c in signals if ((c.contributions or {}).get("passport") or {}).get("level") == lv) for lv in ("A", "B")},
            "watch": sum(1 for c in cands if c.status == "watch"),
            "exclusions": {},
        }
        for c in cands:
            if c.status not in ("signal", "watch"):
                out["exclusions"][c.exclusion_code] = out["exclusions"].get(c.exclusion_code, 0) + 1
        if domain:
            dom_items = [it for it in items if it["domain"] == domain]
            hit = [it["id"] for it in dom_items if any(matches(c.name, terms[str(it["id"])]) for c in signals)]
            out["dataset_signals_in_domain"] = len(dom_items)
            out["dataset_hits_in_top15"] = len(hit)
            out["share_of_top15_from_dataset"] = round(len(hit) / max(len(signals), 1), 3)
            out["recall_of_domain"] = round(len(hit) / len(dom_items), 3)
        return out


async def main_async(args) -> None:
    init_db()
    path = Path(get_settings().model_dir) / (getattr(args, "out", "") or "live_eval.json")
    report = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
    before = path.with_name("live_eval_before.json")
    if args.fresh and path.exists() and not before.exists():
        before.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    plan = []
    if args.fresh:
        report = {"runs": []}  # новый отчёт: старые прогоны (до доработки) не смешиваем с новыми
    if args.queries:
        plan = [(None, q, True) for q in args.queries.split(";")]
    elif args.domains:
        for dom in args.domains.split(";"):
            plan += [(dom, DOMAIN_QUERIES[dom], True), (dom, DOMAIN_QUERIES[dom], False)]
        plan += [(None, q, True) for q in EXTRA_QUERIES] if args.extras else []
    else:
        for dom, q in DOMAIN_QUERIES.items():
            if not args.only_discovery:
                plan.append((dom, q, True))
            plan.append((dom, q, False))
        if not args.only_discovery:
            plan += [(None, q, True) for q in EXTRA_QUERIES]
    if args.nonsense:
        plan = [(None, q, False) for q in NONSENSE_QUERIES] + plan  # сначала — быстрые контрольные отказы
    for dom, q, wl in plan:
        run_id = await run_query(q, wl)
        summary = {"domain": dom, "mode": "с базой отслеживания" if wl else "только обнаружение", **summarize(run_id, dom)}
        report["runs"].append(summary)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        print(json.dumps({k: summary.get(k) for k in ("domain", "mode", "query", "status", "seconds", "n_signals", "passport", "watch", "dataset_hits_in_top15", "recall_of_domain", "new_candidates_in_top")}, ensure_ascii=False), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only-discovery", action="store_true")
    ap.add_argument("--queries", default="")
    ap.add_argument("--domains", default="", help="области через «;» — прогон в обоих режимах")
    ap.add_argument("--extras", action="store_true", help="добавить темы вне датасета")
    ap.add_argument("--nonsense", action="store_true", help="добавить контрольные бессмысленные запросы («Привет»)")
    ap.add_argument("--fresh", action="store_true", help="начать новый live_eval.json (старый сохраняется как live_eval_before.json)")
    ap.add_argument("--out", default="", help="имя файла отчёта в data/model (по умолчанию live_eval.json)")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
