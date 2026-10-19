import runpy, sys, io, contextlib
import numpy as np
from sklearn.metrics import roc_auc_score
SP = sys.argv[2]; sys.argv = ["x", sys.argv[1]]
with contextlib.redirect_stdout(io.StringIO()):
    g = runpy.run_path(SP + "/h10/check.py".replace("/h10/check.py", "/tm_emergence.py"))
rows, y, cut, TM, oot = g["rows"], g["y"], g["cut"], g["TM"], g["out_of_time"]
E6 = ["escore", "burst", "yoon_quadrant", "young_growth", "ladder", "attention_gap"]
T = np.array([r["ind"]["T"] for r in rows])
s = {"base13": oot(TM), "E6only": oot(E6), "13+E6": oot(TM + E6),
     "growth2": np.array([r["features"]["growth2"] for r in rows]),
     "young_growth": np.array([r["ind"]["young_growth"] for r in rows])}
rng = np.random.default_rng(0)
for thr in (50, 150):
    m = np.where(T < thr)[0]
    for a, b in (("growth2", "E6only"), ("base13", "E6only"), ("young_growth", "E6only")):
        d = []
        for _ in range(2000):
            i = rng.choice(m, len(m))
            if len(set(y[i])) == 2:
                d.append(roc_auc_score(y[i], s[b][i]) - roc_auc_score(y[i], s[a][i]))
        print(f"<{thr} works n={len(m)}: {b} - {a} = {np.mean(d):+.3f} CI [{np.percentile(d,2.5):+.3f}, {np.percentile(d,97.5):+.3f}]")
    print("   young_growth alone AUC", round(roc_auc_score(y[m], s["young_growth"][m]), 3))
# Brier/extremeness of E6 probabilities
for k in ("base13", "E6only", "13+E6"):
    p = s[k]; print(k, "share p>0.95:", round(float((p > 0.95).mean()), 3), "brier", round(float(np.mean((p - y) ** 2)), 3))
