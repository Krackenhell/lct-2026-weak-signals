import json, sys, math, numpy as np, statistics as st
sys.path.insert(0,'/home/user/lct-2026-weak-signals/backend')
from app.ml.train import _matrix, _oof, _metrics, _fit, has_evidence
from app.pipeline.features import FEATURES
B='/home/user/lct-2026-weak-signals/backend/data/'
rows=[r for r in json.load(open(B+'model/training_rows.json')) if not r.get('incomplete') and has_evidence(r)]
log=json.load(open(B+'log3.json'))
dm=[x for x in log if 'вопросы' in (x.get('purpose') or '') and x['ok']]
live={a: st.mean([x['response']['answers'][a]['value'] for x in dm if a in x['response']['answers']]) for a in ['specific_tech','mass_adoption','market_leaders','standard','early_stage','independent','hype','novelty','benefit','maturity']}
live.update(textbook=0.5,event=0.5)
obscure={'log_total_works':math.log1p(30),'recent_share':0.8,'growth':1.0,'age_years':3,'wiki_exists':0,'log_wiki_views':0,'log_gh_repos_12m':0,'log_hn_12m':0,'fresh_preprints':0.2,'share_science':1.0,'log_evidence':math.log1p(8),**live}
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
def oof(X,y,C,cw,clip=None):
    o=np.zeros(len(y))
    for tr,te in StratifiedKFold(5,shuffle=True,random_state=42).split(X,y):
        sc=StandardScaler().fit(X[tr]); Z=sc.transform(X[tr]); Zt=sc.transform(X[te])
        if clip: Z=np.clip(Z,-clip,clip); Zt=np.clip(Zt,-clip,clip)
        clf=LogisticRegression(C=C,max_iter=3000,class_weight=cw).fit(Z,y[tr]); o[te]=clf.predict_proba(Zt)[:,1]
    return o
def run(name,feats,C=0.5,cw='balanced',clip=3):
    X,y=_matrix(rows,feats); o=oof(X,y,C,cw,clip); m=_metrics(y,o)
    sc=StandardScaler().fit(X); Z=np.clip(sc.transform(X),-clip,clip); clf=LogisticRegression(C=C,max_iter=3000,class_weight=cw).fit(Z,y)
    xo=np.array([[obscure.get(f,0.5) for f in feats]]); zo=np.clip(sc.transform(xo),-clip,clip)
    po=clf.predict_proba(zo)[0,1]
    print('%-48s F1=%.3f AUC=%.3f Brier=%.3f  p(obscure)=%.3f  share oof p>=0.995: %.2f'%(name,m['f1'],m['roc_auc'],m['brier'],po,(o>=0.995).mean()))
F=list(FEATURES)
run('baseline (23 feats, balanced, C=0.5)',F)
run('no independent',[f for f in F if f!='independent'])
run('no independent/hype/market_leaders',[f for f in F if f not in('independent','hype','market_leaders')])
run('baseline, class_weight=None',F,cw=None)
run('baseline, C=0.1',F,C=0.1)
run('numeric only',[f for f in F if f in ('log_total_works','recent_share','growth','age_years','wiki_exists','log_wiki_views','log_gh_repos_12m','log_hn_12m','fresh_preprints','share_science','log_evidence')])
run('no github/hn (domain-agnostic)',[f for f in F if f not in('log_gh_repos_12m','log_hn_12m')])
