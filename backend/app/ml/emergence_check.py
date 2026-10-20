"""П13: проверка индикаторов импульса роста на машине времени (118 тем, 5 отсечек), без сети.

Протокол — тот же, что в app/ml/timemachine.py: модель учится на темах одних отсечек и оценивает темы отсечки, которую не видела
(leave-one-cutoff-out), метка — «стало массовым к 2026». Критерий успеха записан до прогона (docs/research, П13):
вариант «все индикаторы без отбора» даёт ΔAUC ≥ +0,03 при нижней границе 95 % ДИ > 0 (парный бутстрэп).
Иначе результат публикуется как отрицательный. Публикуются все варианты, включая неудачные.

Запуск: python -m app.ml.emergence_check   Результат: data/model/emergence.json
"""
import json
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

from app.config import get_settings
from app.pipeline.emergence import indicators, reconstruct_series

TM = ["log_works_total", "log_works_recent2", "growth2", "accel", "recent_share3", "age_years",
      "log_nih_recent3", "nih_growth", "log_yc_total", "log_yc_recent2", "log_gh_repos_12m", "log_hn_12m", "wiki_exists"]
IND = ["young_growth", "burst", "escore", "yoon_quadrant"]


def _pct(v: np.ndarray) -> np.ndarray:
    return np.argsort(np.argsort(v)) / max(len(v) - 1, 1)


def main() -> None:
    d = Path(get_settings().model_dir)
    rows = [r for r in json.loads((d / "timemachine.json").read_text(encoding="utf-8"))["results"] if "openalex" not in r["failed_sources"]]
    for r in rows:
        r["ind"] = indicators(r["features"])
    y = np.array([r["label"] for r in rows])
    cut = np.array([r["cutoff"] for r in rows])
    # Квадрант Yoon — относительно других тем той же отсечки (метки не используются).
    for c in set(cut):
        idx = np.where(cut == c)[0]
        vis = _pct(np.array([rows[i]["features"]["log_works_total"] for i in idx]))
        gro = _pct(np.array([rows[i]["features"]["growth2"] for i in idx]))
        for k, i in enumerate(idx):
            rows[i]["ind"]["yoon_quadrant"] = float(gro[k] - vis[k])
    # Проверка восстановления ряда: пересчитанные growth2 и accel совпадают с сохранёнными.
    err = 0.0
    for r in rows:
        s1, s2, s3, s4, _, _ = reconstruct_series(r["features"])
        g = np.log1p((s1 + s2) / 2) - np.log1p((s3 + s4) / 2)
        a = (np.log1p(s1) - np.log1p(s2)) - (np.log1p(s2) - np.log1p(s3))
        err = max(err, abs(g - r["features"]["growth2"]), abs(a - r["features"]["accel"]))

    def oot(feats, C=0.3):
        X = np.array([[{**r["features"], **r["ind"]}[f] for f in feats] for r in rows])
        p = np.zeros(len(rows))
        for c in sorted(set(cut)):
            tr, te = cut != c, cut == c
            sc = StandardScaler().fit(X[tr])
            clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
            p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
        return p

    def paired(pa, pb, n=2000):
        rng = np.random.default_rng(0)
        ds = []
        for _ in range(n):
            i = rng.integers(0, len(y), len(y))
            if len(set(y[i])) == 2:
                ds.append(roc_auc_score(y[i], pb[i]) - roc_auc_score(y[i], pa[i]))
        ds = np.array(ds)
        return round(float(ds.mean()), 3), [round(float(np.percentile(ds, 2.5)), 3), round(float(np.percentile(ds, 97.5)), 3)]

    base = oot(TM)
    small = np.array([r["features"]["log_works_total"] < np.log1p(50) for r in rows])
    out = {"n": len(rows), "reconstruction_max_error": round(float(err), 6), "base_auc": round(float(roc_auc_score(y, base)), 3),
           "single_indicator_auc": {k: round(float(roc_auc_score(y, [r["ind"][k] for r in rows])), 3) for k in IND}, "variants": {}}
    for name, feats in {**{f"+ {k}": TM + [k] for k in IND}, "все индикаторы без отбора (заранее заданный вариант)": TM + IND}.items():
        p = oot(feats)
        dm, ci = paired(base, p)
        out["variants"][name] = {"auc": round(float(roc_auc_score(y, p)), 3), "delta": dm, "ci95": ci}
    if small.sum() > 5 and len(set(y[small])) == 2:
        out["small_topics"] = {"n": int(small.sum()), "base_auc": round(float(roc_auc_score(y[small], base[small])), 3),
                               "young_growth_auc": round(float(roc_auc_score(y[small], [rows[i]["ind"]["young_growth"] for i in np.where(small)[0]])), 3)}
    main_v = out["variants"]["все индикаторы без отбора (заранее заданный вариант)"]
    out["success"] = main_v["delta"] >= 0.03 and main_v["ci95"][0] > 0
    out["verdict"] = ("индикаторы улучшают прогноз «вне времени»" if out["success"]
                      else "отрицательный результат: прибавка ниже заранее заданного порога — публикуем как есть")
    (d / "emergence.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items()}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
