"""Регрессионный замер выдачи на заранее зафиксированных запросах: не стало ли хуже после доработок.

Набор запросов заморожен в data/bench/queries.json (раздел 7 исследования) и не меняется после просмотра результатов.
Метрики — объективные, без ручной разметки:
- контрольные запросы: «Привет» и «почему мирэа лучший вуз» отклоняются; зрелая тема не выдаётся как сигнал;
- 6 областей датасета: сколько сигналов организатора попало в топ (строгое совпадение, как в eval_live) — сравнение с прошлыми
  замерами (сентябрь, 18.10); прогон со сбоем OpenAlex (> 20 % подставленной статистики) помечается недействительным;
- графен и микрофлюидика: сколько «серебряных» технологий из списка экспертов найдено и не попали ли зрелые (PCR, ELISA…);
- замечания экспертов: нет «100%» (оценка выше 0,95 показывается как «> 95%»), у каждого сигнала есть балл и вклады признаков,
  доля русских названий, отклонённых валидатором, доля утверждений справки, подтверждённых Jev;
- время, стоимость, сбои источников.

Квота OpenAlex: перед каждым прогоном проверяется остаток кредитов ключа; если его мало — замер останавливается
(иначе прогоны станут «грязными», как 18.10). --wait-reset ждёт суточного сброса квоты.

    python -m app.ml.regress --sets controls,regression [--wait-reset] [--min-credits 1800]
Результат: data/model/regress.json (дописывается) и docs/ЗАМЕР_ВЫДАЧИ.md.
"""
import argparse
import asyncio
import json
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.collectors.http import openalex_key
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.ml import eval_live
from app.models import Candidate, ModelCall, Run

ROOT = Path(__file__).resolve().parents[3]
DOMAIN_OF = {v: k for k, v in eval_live.DOMAIN_QUERIES.items()}
SCREENS = ROOT / "presentation" / "screens" / "замер"
CHROME = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")

# Прошлые замеры чистого поиска (без базы отслеживания) по 6 областям: попаданий сигналов организатора в топ.
BASELINES = {
    "сентябрь (сданная версия)": "live_eval_before.json",
    "18.10 только наука": "live_eval_science_only.json",
    "18.10 наука + новости": "live_eval_news_baseline.json",
}


def openalex_credits() -> tuple[int | None, int | None]:
    """Остаток кредитов ключа OpenAlex и секунды до сброса (по заголовкам ответа)."""
    try:
        r = httpx.get("https://api.openalex.org/works", params={"per-page": 1, "select": "id", "api_key": openalex_key()}, timeout=20)
        return int(r.headers.get("x-ratelimit-remaining", -1)), int(r.headers.get("x-ratelimit-reset", 0))
    except (httpx.HTTPError, ValueError):
        return None, None


def baseline_hits() -> dict:
    out = {}
    d = get_settings().model_dir
    for label, fname in BASELINES.items():
        p = d / fname
        if not p.exists():
            continue
        rows = [r for r in json.loads(p.read_text(encoding="utf-8"))["runs"] if isinstance(r, dict) and r.get("dataset_hits_in_top15") is not None
                and not (r.get("options") or {}).get("use_watchlist")]
        by_q = {}
        for r in rows:  # последний чистый прогон области
            by_q[r["query"]] = r
        out[label] = {q: {"hits": r["dataset_hits_in_top15"], "signals": r["n_signals"]} for q, r in by_q.items()}
    return out


def extra_metrics(run_id: int, query: str, bench: dict) -> dict:
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        cands = s.query(Candidate).filter_by(run_id=run_id).all()
        signals = [c for c in cands if c.status == "signal"]
        shown = [c for c in cands if c.status in ("signal", "watch")]
        names = " | ".join(c.name.lower() for c in shown)
        silver = bench.get("silver", {}).get(query, [])
        mature = bench.get("mature_controls", {}).get(query, [])
        # По основам слов (первые 7 букв, без «-s»): «3D-printed microfluidics» = «3d-printed microfluidic chips».
        stems = lambda t: {w.rstrip("s")[:7] for w in re.findall(r"[a-z0-9]{3,}", t.lower())}  # noqa: E731
        hit = lambda t: any(stems(t) <= stems(c.name) for c in shown)  # noqa: E731
        claims = [m for m in s.query(ModelCall).filter_by(run_id=run_id, purpose="проверка утверждений досье")]
        ver = [((c.dossier or {}).get("verification") or {}) for c in signals]
        stats = run.stats or {}
        return {
            "status": run.status,
            "silver_found": [t for t in silver if hit(t)] if silver else None,
            "silver_total": len(silver) or None,
            "mature_leaked": [t for t in mature if any(stems(t) <= stems(c.name) for c in signals)] if mature else None,
            "max_p": round(max([c.probability or 0 for c in signals] or [0]), 3),
            "shown_as": "> 95%" if any((c.probability or 0) >= 0.95 for c in signals) else "≤ 95%",
            "signals_with_score": sum(1 for c in signals if ((c.contributions or {}).get("score") or {}).get("final") is not None),
            "signals_with_contributions": sum(1 for c in signals if (c.contributions or {}).get("items")),
            "names_ru_shown": sum(1 for c in shown if c.name_ru),
            "names_ru_rejected": sum(1 for c in shown if (c.contributions or {}).get("name_check")),
            "claims_checked": sum(v.get("checked") or 0 for v in ver),
            "claims_supported": sum(v.get("supported") or 0 for v in ver),
            "claim_calls": len(claims),
            "cost_rub": (stats.get("cost") or {}).get("total_rub"),
            "timing_total": round(sum((stats.get("timing") or {}).values())),
            "sources_failed": {h: v["failed"] for h, v in (stats.get("http") or {}).items() if v.get("failed")},
            "names_sample": names[:300],
        }


def screenshot(run_id: int, label: str) -> str | None:
    """Снимок страницы результата для презентации (если стенд разработки запущен на :8000 и есть Chrome)."""
    if not CHROME.exists():
        return None
    try:
        httpx.get("http://127.0.0.1:8000/api/health", timeout=3)
    except httpx.HTTPError:
        return None
    SCREENS.mkdir(parents=True, exist_ok=True)
    out = SCREENS / f"{label}.png"
    subprocess.run([str(CHROME), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--virtual-time-budget=8000", f"--user-data-dir={Path.home() / '.radar-shot'}", "--window-size=1600,2000",
                    f"--screenshot={out}", f"http://localhost:8000/runs/{run_id}"], timeout=90, capture_output=True)
    return str(out.relative_to(ROOT)) if out.exists() else None


def report_md(results: list[dict]) -> str:
    base = baseline_hits()
    reg = [r for r in results if r.get("domain")]
    lines = [f"# Замер выдачи на зафиксированных запросах — {datetime.now().strftime('%d.%m.%Y %H:%M')}", "",
             "Набор запросов заморожен заранее (`backend/data/bench/queries.json`); метрики — без ручной разметки. "
             "Скрипт: `python -m app.ml.regress`. Сырые данные: `backend/data/model/regress.json`.", ""]
    if reg:
        lines += ["## 6 областей датасета: сигналы организатора в топе (чистый поиск, без базы отслеживания)", "",
                  "| Область | " + " | ".join(base) + " | **сейчас** | сигналов сейчас | время | ₽ | годен |", "|---" * (len(base) + 6) + "|"]
        tot = {k: 0 for k in base}
        now_tot = 0
        for r in reg:
            cells = []
            for k in base:
                b = base[k].get(r["query"])
                cells.append(str(b["hits"]) if b else "—")
                tot[k] += b["hits"] if b else 0
            now_tot += r.get("dataset_hits_in_top15") or 0
            lines.append(f"| {r['domain']} | " + " | ".join(cells) + f" | **{r.get('dataset_hits_in_top15')}** | {r.get('n_signals')} | "
                         f"{r.get('seconds')} с | {r.get('cost_rub')} | {'нет (сбой OpenAlex)' if r.get('degraded') else 'да'} |")
        lines.append("| **Итого** | " + " | ".join(str(v) for v in tot.values()) + f" | **{now_tot}** | | | | |")
        lines += ["", "Совпадение — строгое по словам названия; сигнал организатора, найденный под другим именем, не засчитывается. "
                  "Это нижняя оценка полноты, а не доля полезных карточек.", ""]
    other = [r for r in results if not r.get("domain")]
    if other:
        lines += ["## Остальные запросы", "", "| Запрос | Статус | Сигналов | Серебро | Зрелые в топе | Время | ₽ |", "|---|---|---|---|---|---|---|"]
        for r in other:
            silver = f"{len(r['silver_found'])} из {r['silver_total']}" if r.get("silver_total") else "—"
            mature = ", ".join(r["mature_leaked"]) if r.get("mature_leaked") else ("нет" if r.get("mature_leaked") is not None else "—")
            lines.append(f"| {r['query']} | {r['status']} | {r.get('n_signals')} | {silver} | {mature} | {r.get('seconds')} с | {r.get('cost_rub')} |")
        lines.append("")
    lines += ["## Замечания экспертов — проверка на этих прогонах", "",
              "| Проверка | Результат |", "|---|---|",
              f"| «100%» на экране | максимальная оценка {max([r.get('max_p') or 0 for r in results] or [0])}, показывается как «> 95%» — «100%» не выводится |",
              f"| Ранжирование видно | у {sum(r.get('signals_with_score') or 0 for r in results)} из {sum(r.get('n_signals') or 0 for r in results)} сигналов есть балл места, "
              f"у {sum(r.get('signals_with_contributions') or 0 for r in results)} — вклады признаков |",
              f"| Русские названия | показано {sum(r.get('names_ru_shown') or 0 for r in results)}, отклонено валидатором (показан английский термин) — "
              f"{sum(r.get('names_ru_rejected') or 0 for r in results)} |",
              f"| Проверка справок Jev | подтверждено {sum(r.get('claims_supported') or 0 for r in results)} утверждений из "
              f"{sum(r.get('claims_checked') or 0 for r in results)}, неподтверждённые удалены |", ""]
    return "\n".join(lines)


def keep_awake() -> None:
    """Windows: не засыпать, пока идёт ночной замер (как видеоплеер; системные настройки не меняются)."""
    try:
        import ctypes

        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    except (AttributeError, OSError):
        pass


async def main_async(args) -> None:
    init_db()
    keep_awake()
    s = get_settings()
    bench = json.loads((s.model_dir.parent / "bench" / "queries.json").read_text(encoding="utf-8"))
    queries: list[str] = []
    for name in args.sets.split(","):
        name = name.strip()
        if name == "controls":
            queries += bench["controls"]["reject"] + bench["controls"]["maturity"]
        elif name == "regression":
            queries += bench["regression"]
        elif name == "dev2":
            queries += list(bench["silver"])
        elif name in bench:
            queries += bench[name]
    if args.only:
        queries = [q for q in queries if q in args.only.split(";")]
    if args.wait_reset:
        left, reset = openalex_credits()
        need = args.min_credits + args.credits_per_run * sum(1 for q in queries if q not in bench["controls"]["reject"])
        if left is not None and left < need and reset:
            print(f"Квота OpenAlex: осталось {left}, сброс через {reset // 60} мин — жду", flush=True)
            await asyncio.sleep(reset + 300)
    path = s.model_dir / "regress.json"
    store = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"sessions": []}
    session = {"started": datetime.now(timezone.utc).isoformat(), "sets": args.sets, "results": []}
    store["sessions"].append(session)
    async def one(q: str, idx: int, left) -> None:
        t = time.time()
        run_id = await eval_live.run_query(q, False)
        res = {**eval_live.summarize(run_id, DOMAIN_OF.get(q)), **extra_metrics(run_id, q, bench),
               "domain": DOMAIN_OF.get(q), "openalex_left_before": left}
        res["screenshot"] = await asyncio.to_thread(screenshot, run_id, f"{idx:02d}_{re.sub(r'[^0-9A-Za-zА-Яа-яЁё]+', '_', q)[:40]}")
        session["results"].append(res)
        path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{q}: {res['status']}, сигналов {res.get('n_signals')}, попаданий {res.get('dataset_hits_in_top15')}, {time.time() - t:.0f} с", flush=True)

    # Пачками по --parallel запросов (как на стенде: MAX_PARALLEL_RUNS); квота проверяется перед каждой пачкой.
    for k in range(0, len(queries), args.parallel):
        batch = queries[k:k + args.parallel]
        left, _ = openalex_credits()
        paid = [q for q in batch if q not in bench["controls"]["reject"]]
        if left is not None and 0 <= left < max(args.min_credits, args.credits_per_run * len(paid)) and paid:
            session["stopped"] = f"квота OpenAlex: осталось {left} кредитов — дальше прогоны были бы недействительными"
            print(session["stopped"], flush=True)
            break
        await asyncio.gather(*(one(q, k + n + 1, left) for n, q in enumerate(batch)))
    session["finished"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    all_results = [r for ss in store["sessions"] for r in ss["results"]]
    latest = {}
    for r in all_results:  # последний прогон каждого запроса
        latest[r["query"]] = r
    (ROOT / "docs" / "ЗАМЕР_ВЫДАЧИ.md").write_text(report_md(list(latest.values())), encoding="utf-8")
    print("Отчёт: docs/ЗАМЕР_ВЫДАЧИ.md", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sets", default="controls,regression")
    ap.add_argument("--only", default="")
    ap.add_argument("--wait-reset", action="store_true")
    ap.add_argument("--min-credits", type=int, default=600)
    ap.add_argument("--parallel", type=int, default=2)
    ap.add_argument("--credits-per-run", type=int, default=1300)  # замер 20.10: холодный прогон ≈ 1 240 кредитов OpenAlex
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
