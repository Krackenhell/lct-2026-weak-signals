"""П10 (M3, docs/research): «только LLM» против нашего конвейера.

Для каждой темы — прогон в режиме seed_candidates (GigaChat одним вызовом называет 15 слабых сигналов, дальше те же проверки)
и последний обычный прогон той же темы. Автоматические метрики по сохранённым прогонам:
- доля названий, которые наши фильтры исключили как зрелые, общие, не технологии, нерелевантные, без доказательств;
- доля сигналов и паспортов A/B; доля кандидатов с подтверждением, датированным последними 24 месяцами.
Слепая разметка — по выгрузке (элементы обоих списков перемешаны) — задача людей, здесь не выполняется.

Запуск: python -m app.ml.llm_baseline --queries "q1;q2" [--reuse]   Результат: data/model/llm_baseline.json
"""
import argparse
import asyncio
import json
from datetime import date, timedelta
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal, init_db
from app.models import Candidate, Document, Run
from app.pipeline import runner

FAIL_CODES = {"mature": "зрелые", "broad": "слишком общие", "not_technology": "не технологии", "irrelevant": "нерелевантные",
              "low_evidence": "без доказательств", "low_trust": "только слабые источники", "standard": "стандарты", "product": "продукты",
              "organization": "организации", "paper_title": "заголовки статей", "low_probability": "низкая оценка", "topic_itself": "сама тема"}


def summarize(run_id: int) -> dict:
    cutoff = (date.today() - timedelta(days=730)).isoformat()
    with SessionLocal() as s:
        run = s.get(Run, run_id)
        cands = s.query(Candidate).filter_by(run_id=run_id).all()
        n = len(cands) or 1
        sig = [c for c in cands if c.status == "signal"]
        dated = 0
        for c in cands:
            docs = [s.get(Document, i) for i in (c.document_ids or [])[:20]]
            if any(d and d.published and d.published >= cutoff and d.source_type != "dataset" for d in docs):
                dated += 1
        codes: dict[str, int] = {}
        for c in cands:
            if c.status == "excluded" and c.exclusion_code in FAIL_CODES:
                codes[FAIL_CODES[c.exclusion_code]] = codes.get(FAIL_CODES[c.exclusion_code], 0) + 1
        return {
            "run_id": run_id, "query": run.query, "mode": "только LLM" if (run.options or {}).get("seed_candidates") else "конвейер",
            "candidates": len(cands), "signals": len(sig), "watch": sum(c.status == "watch" for c in cands),
            "passport_ab": sum(((c.contributions or {}).get("passport") or {}).get("level") in ("A", "B") for c in sig),
            "excluded_share": round(sum(codes.values()) / n, 3), "excluded_by": codes,
            "with_dated_doc_24m_share": round(dated / n, 3),
            "signals_list": [c.name for c in sorted(sig, key=lambda c: c.rank or 99)],
        }


async def run_baseline(query: str) -> int:
    with SessionLocal() as s:
        r = Run(query=query, options={"seed_candidates": True, "eval": True})
        s.add(r)
        s.commit()
        rid = r.id
    await runner.execute(rid)
    return rid


def latest_pipeline_run(query: str) -> int | None:
    with SessionLocal() as s:
        for r in s.query(Run).filter(Run.status == "done").order_by(Run.id.desc()).limit(300):
            if r.query.strip().lower() == query.strip().lower() and not (r.options or {}).get("seed_candidates"):
                return r.id
    return None


async def main_async(queries: list[str]) -> None:
    init_db()
    pairs = []
    for q in queries:
        base_id = latest_pipeline_run(q)
        llm_id = await run_baseline(q)
        pairs.append({"query": q, "llm_only": summarize(llm_id), "pipeline": summarize(base_id) if base_id else None})
        print(json.dumps({k: (v if k == "query" else {kk: vv for kk, vv in (v or {}).items() if kk not in ("signals_list",)}) for k, v in pairs[-1].items()},
                         ensure_ascii=False), flush=True)
    llm = [p["llm_only"] for p in pairs]
    total = {
        "llm_only_excluded_share": round(sum(x["excluded_share"] * x["candidates"] for x in llm) / max(sum(x["candidates"] for x in llm), 1), 3),
        "llm_only_dated_share": round(sum(x["with_dated_doc_24m_share"] * x["candidates"] for x in llm) / max(sum(x["candidates"] for x in llm), 1), 3),
        "llm_only_signals": sum(x["signals"] for x in llm),
        "pipeline_signals": sum((p["pipeline"] or {}).get("signals", 0) for p in pairs),
    }
    out = {"date": date.today().isoformat(), "pairs": pairs, "total": total}
    (Path(get_settings().model_dir) / "llm_baseline.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(total, ensure_ascii=False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="технология многослойного графена;микрофлюидные чипы;газлифт в газоконденсатных скважинах;перспективные решения в финтехе")
    asyncio.run(main_async([q.strip() for q in ap.parse_args().queries.split(";") if q.strip()]))


if __name__ == "__main__":
    main()
