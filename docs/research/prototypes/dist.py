import json, statistics as st, math, sys
sys.path.insert(0,'/home/user/lct-2026-weak-signals/backend')
B='/home/user/lct-2026-weak-signals/backend/data/'
rows=json.load(open(B+'model/training_rows.json'))
m=json.load(open(B+'model/signal_model.json'))
feat=m['features']; mean=dict(zip(feat,m['mean'])); scale=dict(zip(feat,m['scale'])); coef=dict(zip(feat,m['coef']))
from collections import Counter
print('rows',len(rows), Counter((r['label'],r['code']) for r in rows))
used=[r for r in rows if r['numeric']['log_total_works']>0]  # evidence rule: openalex finds >=1 work
print('used (works>0):',len(used), Counter(r['label'] for r in used))
ans=['specific_tech','mass_adoption','market_leaders','standard','early_stage','independent','hype','novelty','benefit','textbook','maturity','event']
print('%-15s %6s %6s | %6s %6s | %6s %6s'%('ans','pos_mu','pos_sd','neg_mu','neg_sd','mean','scale'))
for a in ans:
    p=[r['answers'].get(a) for r in used if r['label']==1 and r['answers'].get(a) is not None]
    n=[r['answers'].get(a) for r in used if r['label']==0 and r['answers'].get(a) is not None]
    print('%-15s %6.3f %6.3f | %6.3f %6.3f | %6.3f %6.3f coef=%6.3f'%(a,st.mean(p),st.pstdev(p),st.mean(n),st.pstdev(n),mean[a],scale[a],coef[a]))
# live answers from log3 (Sept live run, Jev)
log=json.load(open(B+'log3.json'))
dm=[x for x in log if 'вопросы' in (x.get('purpose') or '') and x['ok']]
print('live jev answer sets:',len(dm))
for a in ans:
    v=[x['response']['answers'][a]['value'] for x in dm if a in x['response']['answers']]
    if not v: print(a,'absent in live'); continue
    z=[(x-mean[a])/scale[a] for x in v]
    clipped=sum(1 for q in z if abs(q)>=3)
    print('%-15s live_mu=%6.3f sd=%6.3f min=%5.2f max=%5.2f | z_mu=%6.2f clipped(|z|>=3)=%d/%d'%(a,st.mean(v),st.pstdev(v),min(v),max(v),st.mean(z),clipped,len(v)))
