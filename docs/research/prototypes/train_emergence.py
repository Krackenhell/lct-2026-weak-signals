"""Offline: do emergence-style derived features help the organizer-dataset classifier? Same CV as app/ml/train.py."""
import json, math, sys
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, roc_auc_score
from sklearn.model_selection import StratifiedKFold
from sklearn.preprocessing import StandardScaler
rows = json.load(open(sys.argv[1]))
rows = [r for r in rows if not r.get("incomplete") and r["numeric"]["log_total_works"] > 0]
NUM = ["log_total_works","recent_share","growth","age_years","wiki_exists","log_wiki_views","log_gh_repos_12m","log_hn_12m","fresh_preprints","share_science","log_evidence"]
ANS = ["specific_tech","mass_adoption","market_leaders","standard","early_stage","independent","hype","novelty","benefit","textbook","maturity","event"]
def ecdf(vals):
    s=np.sort(vals); return lambda v: np.searchsorted(s, v, side="right")/len(s)
g=np.array([r["numeric"]["growth"] for r in rows]); v=np.array([r["numeric"]["log_total_works"] for r in rows])
for r in rows:
    n=r["numeric"]; T=math.expm1(n["log_total_works"]); rec=n["recent_share"]*T
    r["d"]={"young_growth": n["growth"]/(1+n["age_years"]/5),
            "log_recent3": math.log1p(rec),
            "ladder": float(sum([T>0, n["wiki_exists"]>0, n["log_gh_repos_12m"]>0, n["log_hn_12m"]>0])),
            "attention_gap": n["log_hn_12m"]-math.log1p(rec/3),
            "weak_quadrant_raw": (n["growth"]-g.mean())/g.std() - (n["log_total_works"]-v.mean())/v.std()}
y=np.array([r["label"] for r in rows])
def X(feats): return np.array([[{**r["numeric"],**r["answers"],**r["d"]}.get(f,0.5) for f in feats] for r in rows])
def oof(Xm, seed=42, C=0.5):
    p=np.zeros(len(y))
    for tr,te in StratifiedKFold(5,shuffle=True,random_state=seed).split(Xm,y):
        tr_idx=tr
        # fold-safe percentile quadrant: ECDF from training fold only
        sc=StandardScaler().fit(Xm[tr]); clf=LogisticRegression(C=C,max_iter=2000,class_weight="balanced").fit(sc.transform(Xm[tr]),y[tr])
        p[te]=clf.predict_proba(sc.transform(Xm[te]))[:,1]
    return p
def rep(feats, k=10):
    Xm=X(feats); f1=[];auc=[]
    for s in range(k):
        p=oof(Xm,s); f1.append(f1_score(y,p>=0.5)); auc.append(roc_auc_score(y,p))
    return round(np.mean(f1),3), round(np.std(f1),3), round(np.mean(auc),3)
D=["young_growth","log_recent3","ladder","attention_gap","weak_quadrant_raw"]
print("n",len(y),"pos",y.sum())
for name,feats in {"numeric(11)":NUM,"numeric+D":NUM+D,"all(23)":NUM+ANS,"all+D":NUM+ANS+D,"answers only":ANS,"answers+D":ANS+D}.items():
    print(f"{name:14s} F1 mean/std, AUC mean over 10x5CV:", rep(feats))
for d in D:
    print(" numeric +",d, rep(NUM+[d]))
# single-feature AUCs (label 1 = organizer weak signal)
for f in ["growth","recent_share","log_total_works","age_years"]+D:
    s=np.array([{**r["numeric"],**r["d"]}[f] for r in rows]); print(f"single {f:18s} AUC={roc_auc_score(y,s):.3f}")
