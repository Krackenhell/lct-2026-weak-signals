"""П9, часть «стенд»: пересчёт сохранённых прогонов старой и новой моделью (без сети и без вызовов моделей).

Для каждого прогона: кандидаты, прошедшие фильтры (сигнал, «наблюдать» или исключённые только по низкой оценке),
оцениваются signal_model_prev.json и signal_model.json; сравниваются число кандидатов с оценкой ≥ 0,5 и состав
топ-15 по баллу min(p; 0,95) × (0,6 + 0,4 × релевантность). Ворота: медиана числа кандидатов ≥ 0,5 не ниже базы − 2.
Список вошедших и выпавших — для слепой разметки (сигнал / мусор / зрелое).

Запуск: python -m app.ml.rescore_runs [--since-id N]   Результат: data/model/rescore_h4.json
"""
import argparse
import json
import statistics as st
from pathlib import Path

from app.config import get_settings
from app.db import SessionLocal
from app.ml.model import SignalModel
from app.models import Candidate, Run
from app.pipeline.decide import rank_score

ELIGIBLE = {"signal", "watch"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--since-id", type=int, default=0)
    args = ap.parse_args()
    d = Path(get_settings().model_dir)
    old = SignalModel(**{k: v for k, v in json.loads((d / "signal_model_prev.json").read_text(encoding="utf-8")).items() if k in SignalModel.__dataclass_fields__})
    new = SignalModel.load()
    out, n_old, n_new = [], [], []
    with SessionLocal() as s:
        runs = s.query(Run).filter(Run.status == "done", Run.id > args.since_id).order_by(Run.id).all()
        for r in runs:
            cands = [c for c in s.query(Candidate).filter_by(run_id=r.id).all()
                     if c.features and (c.status in ELIGIBLE or c.exclusion_code == "low_probability")]
            if len(cands) < 3:
                continue
            rows = []
            for c in cands:
                po, pn = old.predict(c.features), new.predict(c.features)
                rows.append({"name": c.name, "status": c.status, "p_old": round(po, 3), "p_new": round(pn, 3),
                             "s_old": rank_score(po, c.relevance or 0), "s_new": rank_score(pn, c.relevance or 0)})
            top = lambda key, p, rows=rows: [x["name"] for x in sorted((x for x in rows if x[p] >= 0.5 and x["status"] != "watch"), key=lambda x: -x[key])][:15]  # noqa: E731
            t_old, t_new = top("s_old", "p_old"), top("s_new", "p_new")
            a, b = sum(x["p_old"] >= 0.5 for x in rows), sum(x["p_new"] >= 0.5 for x in rows)
            n_old.append(a)
            n_new.append(b)
            out.append({"run_id": r.id, "query": r.query, "above_05_old": a, "above_05_new": b,
                        "entered_top": [n for n in t_new if n not in t_old], "left_top": [n for n in t_old if n not in t_new],
                        "p_ge_095_old": sum(x["p_old"] >= 0.95 for x in rows), "p_ge_095_new": sum(x["p_new"] >= 0.95 for x in rows)})
    gate = bool(n_old) and st.median(n_new) >= st.median(n_old) - 2
    rep = {"runs": out, "median_above_05_old": st.median(n_old) if n_old else None, "median_above_05_new": st.median(n_new) if n_new else None,
           "gate_median": gate}
    (d / "rescore_h4.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for x in out:
        print(f"{x['run_id']:>4} {x['query'][:45]:45s} ≥0,5: {x['above_05_old']:>2} → {x['above_05_new']:>2} | ≥0,95: {x['p_ge_095_old']:>2} → {x['p_ge_095_new']:>2} | "
              f"вошли {len(x['entered_top'])}, выпали {len(x['left_top'])}")
    print("медиана ≥ 0,5:", rep["median_above_05_old"], "→", rep["median_above_05_new"], "| ворота:", "пройдены" if gate else "НЕ пройдены")


if __name__ == "__main__":
    main()
