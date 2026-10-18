import runpy, sys, io, contextlib, numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
sys.argv=["x", sys.argv[1]]
with contextlib.redirect_stdout(io.StringIO()):
    g=runpy.run_path("tm_emergence.py")
rows,y,TM,oot=g["rows"],g["y"],g["TM"],g["out_of_time"]
E6=["escore","burst","yoon_quadrant","young_growth","ladder","attention_gap"]
def pak(s):
    k=int(y.sum()); return round(float(y[np.argsort(-s)[:k]].mean()),3)
def p10(s): return round(float(y[np.argsort(-s)[:20]].mean()),3)
for name,f in {"base13":TM,"E6 only":E6,"13+E6":TM+E6}.items():
    p=oot(f); print(name,"AUC",round(roc_auc_score(y,p),3),"P@k",pak(p),"P@20",p10(p),"brier",round(float(np.mean((p-y)**2)),3))
X=np.array([[{**r["features"],**r["ind"]}[f] for f in E6] for r in rows]); sc=StandardScaler().fit(X)
clf=LogisticRegression(C=0.3,max_iter=2000,class_weight="balanced").fit(sc.transform(X),y)
print("E6 weights:",dict(zip(E6,np.round(clf.coef_[0],3))))
# examples: biggest rank gains
pb=oot(TM); pe=oot(E6)
d=sorted(range(len(rows)),key=lambda i:-(pe[i]-pb[i])*(1 if y[i]==1 else -1))
for i in d[:8]: print("helped:",rows[i]["phrase"],rows[i]["cutoff"],"label",y[i],"base",round(pb[i],2),"E6",round(pe[i],2), {k:round(rows[i]["ind"][k],2) for k in ("escore","yoon_quadrant","young_growth","s1","s2","s3","s4")})
for i in d[-5:]: print("hurt:",rows[i]["phrase"],rows[i]["cutoff"],"label",y[i],"base",round(pb[i],2),"E6",round(pe[i],2))
