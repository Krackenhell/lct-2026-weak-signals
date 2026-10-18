"""Offline test: literature emergence indicators on saved time-machine rows (no network).

Reconstructs yearly OpenAlex counts s1..s4 (years c-1..c-4) + older total from the 6 saved
publication features, computes Yoon / Porter / burst / ladder indicators, and evaluates
(a) each indicator alone (AUC), (b) the 13-feature model + new indicators, out-of-time
(leave-one-cutoff-out, same protocol as app/ml/timemachine.py), with paired bootstrap.
"""
import json
import math
import sys

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.preprocessing import StandardScaler

PATH = sys.argv[1]
rows = json.load(open(PATH))["results"]
rows = [r for r in rows if "openalex" not in r["failed_sources"]]
TM = ["log_works_total", "log_works_recent2", "growth2", "accel", "recent_share3", "age_years",
      "log_nih_recent3", "nih_growth", "log_yc_total", "log_yc_recent2", "log_gh_repos_12m", "log_hn_12m", "wiki_exists"]


def reconstruct(f):
    T = math.expm1(f["log_works_total"])
    r2 = math.expm1(f["log_works_recent2"])
    p2 = max(0.0, 2 * math.expm1(math.log1p(r2 / 2) - f["growth2"]))
    s3 = max(0.0, min(p2, f["recent_share3"] * T - r2)) if T else 0.0
    s4 = max(0.0, p2 - s3)
    target = f["accel"] - math.log1p(s3)
    lo, hi = 0.0, r2
    for _ in range(80):  # f(s2) = log1p(r2-s2) - 2 log1p(s2) decreasing in s2
        mid = (lo + hi) / 2
        if math.log1p(r2 - mid) - 2 * math.log1p(mid) > target:
            lo = mid
        else:
            hi = mid
    s2 = (lo + hi) / 2
    s1 = r2 - s2
    older = max(0.0, T - (s1 + s2 + s3 + s4))
    return s1, s2, s3, s4, older, T


def indicators(r):
    f = r["features"]
    s1, s2, s3, s4, older, T = reconstruct(f)
    sq = math.sqrt
    # Porter-style EScore proxy (2*active + recent + slope), sqrt-damped counts
    active = (sq(s1) + sq(s2) + sq(s3)) / 3 - sq(s4 + older / 10)
    recent = sq(s1 + s2) - sq(s3 + s4)
    slope = (sq(s1) - sq(s3)) / 2
    escore = 2 * active + recent + slope
    # Porter gates: persistence (>=3 of last 4 years with records), >=7 records, base share < 15 %
    years_present = sum(1 for v in (s1, s2, s3, s4) if v >= 0.5)
    porter_ok = float(years_present >= 3 and T >= 7 and (older / T if T else 1) < 0.85)
    # Yoon time-weighted DoD increase rate (tw = 0.05), raw counts (no corpus normaliser offline)
    tw, seq = 0.05, [s4, s3, s2, s1]
    w = [x * (1 - tw * (len(seq) - 1 - j)) for j, x in enumerate(seq)]
    rates = [(w[j] - w[j - 1]) / max(w[j - 1], 1.0) for j in range(1, len(w))]
    yoon_rate = float(np.mean(rates))
    # Poisson burst z of last year vs previous three
    mu = (s2 + s3 + s4) / 3
    burst = (s1 - mu) / sq(mu + 1)
    # novelty x growth: young and growing
    young_growth = f["growth2"] / (1 + f["age_years"] / 5)
    # diffusion ladder: how many communities already touch the term
    ladder = sum([T > 0, f["log_nih_recent3"] > 0, f["log_gh_repos_12m"] > 0, f["log_hn_12m"] > 0, f["log_yc_total"] > 0, f["wiki_exists"] > 0])
    # hype positioning: attention (HN) relative to science output
    attention_gap = f["log_hn_12m"] - f["log_works_recent2"]
    return {"s1": s1, "s2": s2, "s3": s3, "s4": s4, "T": T, "escore": escore, "porter_ok": porter_ok, "yoon_rate": yoon_rate,
            "burst": burst, "young_growth": young_growth, "ladder": float(ladder), "attention_gap": attention_gap,
            "log_last_year": math.log1p(s1), "last_share": s1 / T if T else 0.0}


for r in rows:
    r["ind"] = indicators(r)
y = np.array([r["label"] for r in rows])
cut = np.array([r["cutoff"] for r in rows])

# within-cutoff percentiles (Yoon map is relative to the corpus at that moment; no label info used)
def pct(vals):
    order = np.argsort(np.argsort(vals))
    return order / max(len(vals) - 1, 1)

for c in set(cut):
    idx = np.where(cut == c)[0]
    vis = pct(np.array([rows[i]["features"]["log_works_total"] for i in idx]))
    gro = pct(np.array([rows[i]["features"]["growth2"] for i in idx]))
    for k, i in enumerate(idx):
        rows[i]["ind"]["yoon_quadrant"] = float(gro[k] - vis[k])  # high growth, low visibility -> weak signal

# reconstruction sanity: recompute features from s1..s4
err = []
for r in rows:
    i, f = r["ind"], r["features"]
    g = math.log1p((i["s1"] + i["s2"]) / 2) - math.log1p((i["s3"] + i["s4"]) / 2)
    a = (math.log1p(i["s1"]) - math.log1p(i["s2"])) - (math.log1p(i["s2"]) - math.log1p(i["s3"]))
    err.append(max(abs(g - f["growth2"]), abs(a - f["accel"])))
print("reconstruction max abs error growth2/accel:", round(max(err), 4))


def auc_by_cut(s):
    return {int(c): round(float(roc_auc_score(y[cut == c], s[cut == c])), 3) for c in sorted(set(cut)) if len(set(y[cut == c])) == 2}


print("\n=== single indicators (AUC: label 1 = became mainstream by 2026) ===")
single = {}
for k in ["escore", "yoon_rate", "burst", "young_growth", "ladder", "attention_gap", "yoon_quadrant", "porter_ok", "log_last_year", "last_share"]:
    s = np.array([r["ind"][k] for r in rows])
    single[k] = round(float(roc_auc_score(y, s)), 3)
    print(f"{k:15s} AUC={single[k]:.3f}  by_cutoff={auc_by_cut(s)}")
s = np.array([r["features"]["growth2"] for r in rows])
print(f"{'growth2(base)':15s} AUC={roc_auc_score(y, s):.3f}  by_cutoff={auc_by_cut(s)}")


def out_of_time(feats, C=0.3):
    X = np.array([[{**r["features"], **r["ind"]}[f] for f in feats] for r in rows])
    p = np.zeros(len(rows))
    for c in sorted(set(cut)):
        tr, te = cut != c, cut == c
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
        p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    return p


def paired(pa, pb, n=2000, seed=0):
    rng = np.random.default_rng(seed)
    d = []
    for _ in range(n):
        i = rng.integers(0, len(y), len(y))
        if len(set(y[i])) == 2:
            d.append(roc_auc_score(y[i], pb[i]) - roc_auc_score(y[i], pa[i]))
    d = np.array(d)
    return round(float(np.mean(d)), 3), [round(float(np.percentile(d, 2.5)), 3), round(float(np.percentile(d, 97.5)), 3)], round(float((d > 0).mean()), 3)


base = out_of_time(TM)
print("\n=== out-of-time model (leave-one-cutoff-out), n =", len(rows), "===")
print("base 13 feats AUC", round(roc_auc_score(y, base), 3), auc_by_cut(base))
variants = {
    "+escore": TM + ["escore"],
    "+burst": TM + ["burst"],
    "+yoon_quadrant": TM + ["yoon_quadrant"],
    "+young_growth": TM + ["young_growth"],
    "+ladder": TM + ["ladder"],
    "+attention_gap": TM + ["attention_gap"],
    "+all emergence (6)": TM + ["escore", "burst", "yoon_quadrant", "young_growth", "ladder", "attention_gap"],
    "compact: growth2,accel,escore,yoon_quadrant,ladder,log_nih_recent3,wiki_exists": ["growth2", "accel", "escore", "yoon_quadrant", "ladder", "log_nih_recent3", "wiki_exists"],
}
for name, feats in variants.items():
    p = out_of_time(feats)
    m, ci, share = paired(base, p)
    print(f"{name:75s} AUC={roc_auc_score(y, p):.3f}  dAUC={m:+.3f} CI95={ci} P(better)={share}  by_cut={auc_by_cut(p)}")

# Porter gate pass-rate by label
po = np.array([r["ind"]["porter_ok"] for r in rows])
print("\nPorter persistence gate pass rate: trend=1:", round(po[y == 1].mean(), 3), " trend=0:", round(po[y == 0].mean(), 3))
