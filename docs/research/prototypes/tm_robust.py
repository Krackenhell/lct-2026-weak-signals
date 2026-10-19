import runpy, sys, numpy as np
from sklearn.metrics import roc_auc_score
sys.argv=["x", sys.argv[1]]
import io, contextlib
buf=io.StringIO()
with contextlib.redirect_stdout(buf):
    g=runpy.run_path("tm_emergence.py")
rows,y,TM,oot,paired=g["rows"],g["y"],g["TM"],g["out_of_time"],g["paired"]
E6=["escore","burst","yoon_quadrant","young_growth","ladder","attention_gap"]
for C in (0.05,0.3,1.0):
    b=oot(TM,C); p=oot(TM+E6,C); print("C",C,"base",round(roc_auc_score(y,b),3),"+E6",round(roc_auc_score(y,p),3), paired(b,p))
# leave one indicator out of E6
b=oot(TM)
for k in E6:
    feats=TM+[e for e in E6 if e!=k]; p=oot(feats); print("drop",k,round(roc_auc_score(y,p),3))
# E6 without transductive percentile
p=oot(TM+[e for e in E6 if e!="yoon_quadrant"]); print("E6 w/o yoon_quadrant", round(roc_auc_score(y,p),3), paired(b,p))
# noise control: 6 random features, 200 draws
rng=np.random.default_rng(1); aucs=[]
for t in range(200):
    for r in rows:
        for j in range(6): r["ind"][f"n{j}"]=rng.normal()
    aucs.append(roc_auc_score(y,oot(TM+[f"n{j}" for j in range(6)])))
aucs=np.array(aucs); print("noise control: mean",round(aucs.mean(),3),"p95",round(np.percentile(aucs,95),3),"max",round(aucs.max(),3), "share>=0.745", (aucs>=0.745).mean())
# indicators only (no 13 base)
for feats in (E6, ["growth2","accel"]+E6):
    p=oot(feats); print(feats, round(roc_auc_score(y,p),3))
