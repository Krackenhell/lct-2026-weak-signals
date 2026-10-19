import runpy, sys, io, contextlib, math, itertools
import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
SP = sys.argv[2]
sys.argv = ["x", sys.argv[1]]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(SP + "/tm_emergence.py")
rows, y, cut, TM, oot, paired = g["rows"], g["y"], g["cut"], g["TM"], g["out_of_time"], g["paired"]
E6 = ["escore", "burst", "yoon_quadrant", "young_growth", "ladder", "attention_gap"]
ALL = ["escore", "yoon_rate", "burst", "young_growth", "ladder", "attention_gap", "yoon_quadrant", "porter_ok", "log_last_year", "last_share"]
auc = lambda s: round(float(roc_auc_score(y, s)), 3)
base = oot(TM)
print("base", auc(base), " +E6", auc(oot(TM + E6)))

# 1) non-transductive yoon quadrant: test-cutoff percentiles against TRAINING cutoffs' reference distribution
#    (this is what the live plan does: fixed reference = time-machine rows)
def oot_fixedref(feats, C=0.3):
    p = np.zeros(len(rows))
    for c in sorted(set(cut)):
        tr, te = cut != c, cut == c
        refv = np.array([rows[i]["features"]["log_works_total"] for i in np.where(tr)[0]])
        refg = np.array([rows[i]["features"]["growth2"] for i in np.where(tr)[0]])
        def q(i):
            f = rows[i]["features"]
            return float((refg < f["growth2"]).mean() - (refv < f["log_works_total"]).mean())
        X = []
        for i in range(len(rows)):
            d = {**rows[i]["features"], **rows[i]["ind"]}
            # training rows: within-own-cutoff quadrant replaced by pooled-train reference too (consistent)
            d["yoon_quadrant"] = q(i)
            X.append([d[f] for f in feats])
        X = np.array(X)
        sc = StandardScaler().fit(X[tr])
        clf = LogisticRegression(C=C, max_iter=2000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
        p[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
    return p
pf = oot_fixedref(TM + E6)
print("1) +E6 with fixed (train-cutoff) reference for yoon_quadrant:", auc(pf), paired(base, pf))
pf6 = oot_fixedref(E6)
print("   E6 only, fixed ref:", auc(pf6), paired(base, pf6))

# 2) drop escore (its fitted sign is negative -> contradicts 'EScore = emergence' story)
p = oot(TM + [e for e in E6 if e != "escore"]); print("2) +E5 (no escore):", auc(p), paired(base, p))
# 3) no selection: base + ALL 10 tried indicators
p = oot(TM + ALL); print("3) +ALL 10 tried indicators (no subset selection):", auc(p), paired(base, p))
# 4) how special is E6 among 6-subsets of the 10 tried indicators?
res = []
for comb in itertools.combinations(ALL, 6):
    res.append((auc(oot(TM + list(comb))), comb))
res.sort(reverse=True)
a = np.array([r[0] for r in res])
print(f"4) 6-subsets of 10 tried: n={len(a)}, median={np.median(a):.3f}, p90={np.percentile(a,90):.3f}, max={a.max():.3f}; rank of E6 =",
      1 + sum(1 for r in res if r[0] > auc(oot(TM + E6))))
# 5) nested selection: choose subset inside training cutoffs only (inner LOCO), score held-out cutoff
cands = [list(c) for c in itertools.combinations(ALL, 6)]
pn = np.zeros(len(rows))
for c in sorted(set(cut)):
    trc = [k for k in sorted(set(cut)) if k != c]
    best, bestauc = None, -1
    for feats in cands[::3]:  # subsample for speed
        X = np.array([[{**r["features"], **r["ind"]}[f] for f in TM + feats] for r in rows])
        pi = np.zeros(len(rows)); m = cut != c
        for c2 in trc:
            tr, te = m & (cut != c2), cut == c2
            sc = StandardScaler().fit(X[tr]); clf = LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
            pi[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
        a_in = roc_auc_score(y[m], pi[m])
        if a_in > bestauc: best, bestauc = feats, a_in
    X = np.array([[{**r["features"], **r["ind"]}[f] for f in TM + best] for r in rows])
    tr, te = cut != c, cut == c
    sc = StandardScaler().fit(X[tr]); clf = LogisticRegression(C=0.3, max_iter=2000, class_weight="balanced").fit(sc.transform(X[tr]), y[tr])
    pn[te] = clf.predict_proba(sc.transform(X[te]))[:, 1]
print("5) nested subset selection (honest for forking paths):", auc(pn), paired(base, pn))

# 6) regime that matters live: SMALL topics at cutoff
T = np.array([r["ind"]["T"] for r in rows]); r4 = np.array([r["ind"]["s1"] + r["ind"]["s2"] + r["ind"]["s3"] + r["ind"]["s4"] for r in rows])
pe = oot(TM + E6); pe6 = oot(E6)
gr = np.array([r["features"]["growth2"] for r in rows])
for thr in (50, 150, 500):
    m = T < thr
    if len(set(y[m])) < 2: continue
    print(f"6) topics with <{thr} works at cutoff: n={m.sum()} pos={y[m].sum()}  base={roc_auc_score(y[m], base[m]):.3f}  13+E6={roc_auc_score(y[m], pe[m]):.3f}  E6={roc_auc_score(y[m], pe6[m]):.3f}  growth2={roc_auc_score(y[m], gr[m]):.3f}")
m = r4 >= 5
print(f"   gate >=5 works in last 4y passes: {m.sum()} of {len(rows)}")
