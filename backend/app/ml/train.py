"""Этап 1 ТЗ: обучение и оценка модели на датасете.

Положительные примеры — 100 слабых сигналов организатора. Отрицательные — наш набор
зрелых технологий, стандартов, хайпа и слишком общих областей (data/seed/negatives.json).
Для каждого примера собираются доказательства из открытых источников тем же кодом,
что и при живом поиске, затем считаются признаки и обучается логистическая регрессия.

Запуск:
    python -m app.ml.train                 # собрать признаки (с кэшем) и обучить
    python -m app.ml.train --refit         # только переобучить по сохранённым признакам
    python -m app.ml.train --reask         # заново опросить decision-модель по сохранённым доказательствам
"""
import argparse
import asyncio
import json
import logging
from datetime import date
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler

from app.collectors.http import HttpClient
from app.config import get_settings
from app.decision import get_decision_model
from app.ml.model import SignalModel
from app.pipeline import evidence as evidence_mod
from app.pipeline.features import ANSWERS, FEATURES, NUMERIC, answer_features, numeric_features
from app.pipeline.questions import QUESTIONS, build_state

log = logging.getLogger("train")
# Дата отсечения для обучения фиксирована, чтобы признаки были воспроизводимы.
TRAIN_DATE = date(2026, 9, 23)


def load_examples() -> list[dict]:
    s = get_settings()
    seed = Path(s.seed_dir)
    pos = json.loads((seed / "weak_signals_2026.json").read_text(encoding="utf-8"))
    terms = json.loads((seed / "positive_terms.json").read_text(encoding="utf-8"))
    neg = json.loads((seed / "negatives.json").read_text(encoding="utf-8"))["items"]
    rows = []
    for p in pos:
        rows.append({"key": f"pos-{p['id']}", "label": 1, "name": p["name"], "domain": p["domain"], "code": "signal", "phrase": terms[str(p["id"])][0]})
    for i, n in enumerate(neg):
        rows.append({"key": f"neg-{i}", "label": 0, "name": n["name_ru"], "domain": n["domain"], "code": n["code"], "phrase": n["terms"][0]})
    return rows


async def collect(rows: list[dict], concurrency: int = 6) -> tuple[list[dict], dict]:
    """Собирает доказательства и числовые признаки для каждого примера."""
    http = HttpClient()
    sem = asyncio.Semaphore(concurrency)
    evidence_store: dict = {}
    done = 0

    async def one(r):
        nonlocal done
        async with sem:
            ev = await evidence_mod.gather(http, r["phrase"], TRAIN_DATE, with_news=False, with_repos=False)
        r["numeric"] = numeric_features(ev)
        r["failed_sources"] = sorted(set(ev.failed))
        r["n_docs"] = len(ev.docs)
        evidence_store[r["key"]] = evidence_mod.evidence_items(ev)
        done += 1
        if done % 10 == 0:
            log.info("collected %d/%d", done, len(rows))

    await asyncio.gather(*(one(r) for r in rows))
    log.info("http stats: %s", http.stats)
    await http.close()
    return rows, evidence_store


async def ask_all(rows: list[dict], evidence_store: dict, provider: str | None = None) -> str:
    model = get_decision_model(provider)
    sem = asyncio.Semaphore(8)

    async def one(r):
        state = build_state(r["phrase"], "", evidence_store.get(r["key"], []))
        async with sem:
            res = await model.ask(state, QUESTIONS)
        r["answers"] = answer_features(res.answers)
        r["decision_ok"] = res.ok

    await asyncio.gather(*(one(r) for r in rows))
    return f"{model.provider}:{model.model}"


def _matrix(rows, feats):
    X = np.array([[{**r["numeric"], **r["answers"]}[f] for f in feats] for r in rows], dtype=float)
    y = np.array([r["label"] for r in rows])
    return X, y


def _fit(X, y, C=0.5):
    sc = StandardScaler().fit(X)
    clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X), y)
    return sc, clf


def _oof(X, y, groups=None, C=0.5, seed=42):
    oof = np.zeros(len(y))
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed)
    for tr, te in skf.split(X, y):
        sc, clf = _fit(X[tr], y[tr], C)
        oof[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    return oof


def _metrics(y, p, thr=0.5) -> dict:
    pred = (p >= thr).astype(int)
    return {
        "precision": round(float(precision_score(y, pred, zero_division=0)), 3),
        "recall": round(float(recall_score(y, pred, zero_division=0)), 3),
        "f1": round(float(f1_score(y, pred, zero_division=0)), 3),
        "accuracy": round(float((pred == y).mean()), 3),
        "roc_auc": round(float(roc_auc_score(y, p)), 3),
        "brier": round(float(brier_score_loss(y, p)), 3),
    }


def evaluate_and_fit(rows: list[dict], provider: str) -> dict:
    X, y = _matrix(rows, FEATURES)
    oof = _oof(X, y)
    report = {"provider": provider, "n": int(len(y)), "n_pos": int(y.sum()), "n_neg": int((1 - y).sum()), "train_date": TRAIN_DATE.isoformat()}
    report["cv5"] = _metrics(y, oof)
    report["confident_75"] = {
        "share_of_positives_above_075": round(float((oof[y == 1] >= 0.75).mean()), 3),
        "precision_above_075": round(float(y[oof >= 0.75].mean()) if (oof >= 0.75).any() else 0.0, 3),
    }

    # Ablation: какой вклад дают группы признаков.
    report["ablation"] = {}
    for name, feats in {"numeric_only": NUMERIC, "decision_model_only": ANSWERS, "all": FEATURES}.items():
        Xa, _ = _matrix(rows, feats)
        report["ablation"][name] = _metrics(y, _oof(Xa, y))

    # Перенос на новую область: обучаемся без одной области, проверяем на ней.
    domains = sorted({r["domain"] for r in rows if r["label"] == 1})
    lodo = {}
    for d in domains:
        tr = np.array([r["domain"] != d for r in rows])
        te = ~tr
        sc, clf = _fit(X[tr], y[tr])
        p = clf.predict_proba(sc.transform(X[te]))[:, 1]
        lodo[d] = _metrics(y[te], p) if len(set(y[te])) > 1 else {"recall": round(float(((p >= 0.5) == y[te]).mean()), 3)}
    report["leave_one_domain_out"] = lodo

    # Полнота по областям датасета организатора (out-of-fold).
    report["recall_by_domain"] = {
        d: round(float(np.mean([oof[i] >= 0.5 for i, r in enumerate(rows) if r["label"] == 1 and r["domain"] == d])), 3) for d in domains
    }
    report["errors"] = sorted(
        [{"name": r["name"], "label": r["label"], "code": r["code"], "p": round(float(oof[i]), 3)} for i, r in enumerate(rows) if (oof[i] >= 0.5) != bool(r["label"])],
        key=lambda e: -abs(e["p"] - 0.5),
    )[:40]

    sc, clf = _fit(X, y)
    model = SignalModel(
        features=list(FEATURES),
        mean=[float(v) for v in sc.mean_],
        scale=[float(v) for v in sc.scale_],
        coef=[float(v) for v in clf.coef_[0]],
        intercept=float(clf.intercept_[0]),
        meta={"provider": provider, "trained_on": report["n"], "train_date": TRAIN_DATE.isoformat(), "cv5": report["cv5"]},
    )
    model.save()
    report["weights"] = sorted(
        [{"feature": f, "weight": round(c, 3)} for f, c in zip(FEATURES, model.coef)], key=lambda r: -abs(r["weight"])
    )
    return report


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--refit", action="store_true")
    ap.add_argument("--reask", action="store_true")
    ap.add_argument("--provider", default=None)
    args = ap.parse_args()

    s = get_settings()
    out = Path(s.model_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows_path, ev_path = out / "training_rows.json", out / "training_evidence.json"

    if args.refit or args.reask:
        rows = json.loads(rows_path.read_text(encoding="utf-8"))
        evidence_store = json.loads(ev_path.read_text(encoding="utf-8"))
        provider = rows[0].get("provider", "unknown") if rows else "unknown"
    else:
        rows, evidence_store = asyncio.run(collect(load_examples()))
        ev_path.write_text(json.dumps(evidence_store, ensure_ascii=False), encoding="utf-8")
        args.reask = True

    if args.reask:
        provider = asyncio.run(ask_all(rows, evidence_store, args.provider))
        for r in rows:
            r["provider"] = provider
        rows_path.write_text(json.dumps(rows, ensure_ascii=False, indent=0), encoding="utf-8")

    report = evaluate_and_fit(rows, provider)
    (out / "metrics.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    log.info("CV5: %s", report["cv5"])
    log.info("ablation: %s", report["ablation"])
    log.info("LODO: %s", report["leave_one_domain_out"])


if __name__ == "__main__":
    main()
