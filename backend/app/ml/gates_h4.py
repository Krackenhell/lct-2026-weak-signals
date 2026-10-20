"""П9 (H4, docs/research): офлайн-ворота для классификатора без бонуса «нет GitHub = сигнал».

Сравниваются, по одному протоколу (повтор 10×5, отсечка ±3σ при предсказании — как в model._z):
- база — текущий набор признаков;
- кандидат — без log_gh_repos_12m и log_hn_12m (вне IT почти у всех ноль, и ноль давал +1,9 логита) и без трёх
  признаков-ответов Jev с перевёрнутым знаком (independent, early_stage, benefit: вес против смысла вопроса).
Ворота (записаны в исследовании до прогона):
  повторный F1 ≥ база − 0,02; AUC ≥ база − 0,01; падение F1 в любом домене LODO ≤ 0,10; 0 противоречий знаков;
  чувствительность к шуму ответов Jev (sd 0,1) ≤ 0,75 × база; профиль «только рынок» ≥ база − 0,05; GitHub-инвариантность.
Кандидат выкатывается (train.MODEL_EXCLUDE), только если пройдены все ворота.

Запуск: python -m app.ml.gates_h4   Результат: data/model/gates_h4.json
"""
import json
import math
import statistics as st
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold

from app.config import get_settings
from app.ml import train as T
from app.pipeline.features import ANSWERS, FEATURES

# Ожидаемый знак веса по смыслу признака: «+» — признак говорит «рано / ново», «−» — «зрело / известно».
SIGN = {"log_total_works": -1, "recent_share": 1, "growth": 1, "age_years": -1, "wiki_exists": -1, "log_wiki_views": -1,
        "fresh_preprints": 1, "share_science": 1, "specific_tech": 1, "mass_adoption": -1, "market_leaders": -1, "standard": -1,
        "early_stage": 1, "independent": 1, "hype": -1, "novelty": 1, "benefit": 1, "textbook": -1, "maturity": -1, "event": 1,
        "log_gh_repos_12m": -1, "log_hn_12m": -1}
CANDIDATE_EXCLUDE = ("log_gh_repos_12m", "log_hn_12m", "independent", "early_stage", "benefit")
DOMAINS = ["Защита ИИ", "Роботы", "Финтех", "Инфраструктура ИИ"]


class Model:
    """Та же модель, что в проде: StandardScaler + логистическая регрессия (C = 0,5, сбалансированные веса),
    при предсказании отклонение ограничено ±3σ."""

    def __init__(self, X, y):
        self.sc, self.clf = T._fit(X, y)

    def z(self, X):
        return np.clip(self.sc.transform(X), -3, 3)

    def logit(self, X):
        return self.z(X) @ self.clf.coef_[0] + self.clf.intercept_[0]

    def p(self, X):
        return 1 / (1 + np.exp(-self.logit(X)))


def live_answers() -> dict:
    """Средние живые ответы Jev из журнала вызовов локальной базы (прогоны 17–19.10); без журнала — 0,5."""
    try:
        from app.db import SessionLocal
        from app.models import ModelCall

        with SessionLocal() as s:
            calls = s.query(ModelCall).filter(ModelCall.provider == "jev", ModelCall.ok.is_(True)).order_by(ModelCall.id.desc()).limit(3000).all()
        vals: dict[str, list] = {}
        for c in calls:
            for k, v in ((c.response or {}).get("answers") or {}).items():
                if k in ANSWERS and isinstance(v, dict) and v.get("value") is not None:
                    vals.setdefault(k, []).append(float(v["value"]))
        return {a: round(st.mean(vals[a]), 3) if vals.get(a) else 0.5 for a in ANSWERS}
    except Exception:  # noqa: BLE001 — без базы ворота считаются на нейтральных ответах
        return {a: 0.5 for a in ANSWERS}


def profiles(live: dict) -> dict:
    market = {"log_total_works": 0.0, "recent_share": 0.0, "growth": 0.0, "age_years": 0, "wiki_exists": 0, "log_wiki_views": 0,
              "log_gh_repos_12m": math.log1p(150), "log_hn_12m": math.log1p(12), "fresh_preprints": 0.0, "share_science": 0.0,
              "log_evidence": math.log1p(10), **live, "novelty": 0.85, "event": 0.8, "maturity": 0.25}
    obscure = {"log_total_works": math.log1p(30), "recent_share": 0.8, "growth": 1.0, "age_years": 3, "wiki_exists": 0, "log_wiki_views": 0,
               "log_gh_repos_12m": 0, "log_hn_12m": 0, "fresh_preprints": 0.2, "share_science": 1.0, "log_evidence": math.log1p(8), **live}
    return {"только рынок": market, "малоизвестная академическая фраза": obscure}


def evaluate(rows, feats, live) -> dict:
    X, y = T._matrix(rows, feats)
    f1s, aucs = [], []
    for seed in range(10):
        o = np.zeros(len(y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            o[te] = Model(X[tr], y[tr]).p(X[te])
        f1s.append(f1_score(y, o >= 0.5))
        aucs.append(roc_auc_score(y, o))
    lodo = {}
    for d in DOMAINS:
        tr = np.array([r["domain"] != d for r in rows])
        if tr.all() or (~tr).sum() == 0 or len(set(y[~tr])) < 2:
            continue
        lodo[d] = round(float(f1_score(y[~tr], Model(X[tr], y[tr]).p(X[~tr]) >= 0.5)), 3)
    # Чувствительность к шуму ответов Jev (sd 0,1): средний |Δлогит| на невиденных примерах.
    rng = np.random.default_rng(0)
    ans_idx = [i for i, f in enumerate(feats) if f in ANSWERS]
    dl = []
    for seed in range(5):
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            m = Model(X[tr], y[tr])
            Xd = X[te].copy()
            Xd[:, ans_idx] = np.clip(Xd[:, ans_idx] + rng.normal(0, 0.1, (len(te), len(ans_idx))), 0, 1)
            dl.append(float(np.abs(m.logit(Xd) - m.logit(X[te])).mean()))
    m = Model(X, y)
    w = dict(zip(feats, m.clf.coef_[0], strict=True))
    prof = {k: round(float(m.p(np.array([[v.get(f, 0.5) for f in feats]]))[0]), 3) for k, v in profiles(live).items()}
    # GitHub-инвариантность: при нуле репозиториев и обсуждений оценка не меняется.
    base_x = profiles(live)["малоизвестная академическая фраза"]
    gh = {**base_x, "log_gh_repos_12m": math.log1p(500), "log_hn_12m": math.log1p(30)}
    dp = float(m.p(np.array([[gh.get(f, 0.5) for f in feats]]))[0] - m.p(np.array([[base_x.get(f, 0.5) for f in feats]]))[0])
    return {
        "features": feats, "f1_repeated": round(float(np.mean(f1s)), 3), "f1_std": round(float(np.std(f1s)), 3), "auc": round(float(np.mean(aucs)), 3),
        "lodo_f1": lodo, "noise_dlogit": round(float(np.mean(dl)), 3), "profiles": prof, "github_dp": round(dp, 4),
        "sign_contradictions": [f for f, v in w.items() if SIGN.get(f, 0) * v < -1e-6],
        "weights": {f: round(float(v), 3) for f, v in sorted(w.items(), key=lambda kv: -abs(kv[1]))},
    }


def gates(base: dict, cand: dict) -> dict:
    g = {
        "F1 ≥ база − 0,02": cand["f1_repeated"] >= base["f1_repeated"] - 0.02,
        "AUC ≥ база − 0,01": cand["auc"] >= base["auc"] - 0.01,
        "LODO: падение ≤ 0,10 в каждом домене": all(cand["lodo_f1"].get(d, 0) >= v - 0.10 for d, v in base["lodo_f1"].items()),
        "0 противоречий знаков": not cand["sign_contradictions"],
        "шум ≤ 0,75 × база": cand["noise_dlogit"] <= 0.75 * base["noise_dlogit"],
        "«только рынок» ≥ база − 0,05": cand["profiles"]["только рынок"] >= base["profiles"]["только рынок"] - 0.05,
        "GitHub-инвариантность (Δp = 0)": abs(cand["github_dp"]) < 1e-9,
    }
    return {"gates": g, "passed": all(g.values())}


def main() -> None:
    s = get_settings()
    rows = json.loads((Path(s.model_dir) / "training_rows.json").read_text(encoding="utf-8"))
    rows = [r for r in rows if not r.get("incomplete") and T.has_evidence(r)]
    feats = T._usable(rows, FEATURES)
    live = live_answers()
    base = evaluate(rows, feats, live)
    cand = evaluate(rows, [f for f in feats if f not in CANDIDATE_EXCLUDE], live)
    out = {"n": len(rows), "live_answers": live, "base": base, "candidate": cand, "candidate_excludes": list(CANDIDATE_EXCLUDE), **gates(base, cand)}
    (Path(s.model_dir) / "gates_h4.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    for k in ("f1_repeated", "auc", "lodo_f1", "noise_dlogit", "profiles", "github_dp", "sign_contradictions"):
        print(f"{k:20s} база {base[k]}  |  кандидат {cand[k]}")
    for k, v in out["gates"].items():
        print(("✓ " if v else "✗ ") + k)
    print("РЕШЕНИЕ:", "выкатываем кандидата" if out["passed"] else "не выкатываем, остаётся база")


if __name__ == "__main__":
    main()
