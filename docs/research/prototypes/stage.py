import json, collections, re
from scipy.stats import spearmanr
R='/home/user/lct-2026-weak-signals/backend/'
d=json.load(open(R+'data/seed/weak_signals_2026.json'))
rows=json.load(open(R+'data/model/training_rows.json'))
pos={r['key']:r for r in rows if r['label']==1}
print('pos rows',len(pos), 'keys sample', list(pos)[:3])
def stage_num(s):
    s=s.lower()
    first=re.split(r'→|/ |\(|,', s)[0]
    # take first stage mentioned as main
    def lvl(t):
        if 'концеп' in t or t.strip().startswith('исслед'): return 1
        if 'прототип' in t or 'poc' in t: return 2
        if 'пилот' in t: return 3
        if 'внедрен' in t or 'серия' in t or 'поставк' in t: return 4
        return None
    a=lvl(first)
    parts=[lvl(p) for p in re.split(r'→', s)]
    parts=[p for p in parts if p]
    return a, (sum(parts[:2])/len(parts[:2]) if parts else None), max(parts) if parts else None
def trend_num(t):
    t=t.lower()
    if 'быстро' in t: return 2
    if 'стабил' in t: return 0
    return 1
X=[]
for x in d:
    r=pos.get(f"pos-{x['id']}")
    if not r: continue
    a,avg,mx=stage_num(x['stage'])
    X.append(dict(id=x['id'],stage_first=a,stage_avg=avg,stage_max=mx,trend=trend_num(x['trend']),score=x['score'],
                  mat=r['answers'].get('maturity'),ev=r['answers'].get('event'),early=r['answers'].get('early_stage'),
                  n_docs=r.get('n_docs'),n_all=r.get('n_docs_all'), growth=r['numeric']['growth']))
print(len(X))
print('stage_first counts',collections.Counter(z['stage_first'] for z in X))
for k in ['stage_first','stage_avg','stage_max','score','trend']:
    for f in ['mat','ev','early','growth']:
        v=[(z[k],z[f]) for z in X if z[k] is not None and z[f] is not None]
        print(k,f,len(v),round(spearmanr([a for a,b in v],[b for a,b in v]).correlation,3))
# score vs stage+trend
import numpy as np
v=[(z['stage_first'],z['trend'],z['score']) for z in X if z['stage_first']]
pred=[s+1+t for s,t,_ in v]
print('score==stage_first+1+trend exact', np.mean([p==sc for p,(_,_,sc) in zip(pred,v)]), 'within1', np.mean([abs(p-sc)<=1 for p,(_,_,sc) in zip(pred,v)]))
pred=[s+2 for s,t,_ in v]
print('score==stage+2', np.mean([p==sc for p,(_,_,sc) in zip(pred,v)]), np.mean([abs(p-sc)<=1 for p,(_,_,sc) in zip(pred,v)]))
pred=[5]*len(v)
print('score==5 const', np.mean([p==sc for p,(_,_,sc) in zip(pred,v)]), np.mean([abs(p-sc)<=1 for p,(_,_,sc) in zip(pred,v)]))
# maturity -> stage mapping: maturity 6 levels 0..1 -> level idx 0..5
def mat2stage(m):
    i=round(m*5)
    return {0:1,1:2,2:3,3:4,4:4,5:4}[i]
v=[(z['stage_first'],mat2stage(z['mat'])) for z in X if z['stage_first'] and z['mat'] is not None]
print('mat->stage exact',np.mean([a==b for a,b in v]),'within1',np.mean([abs(a-b)<=1 for a,b in v]))
print('maj class exact', max(collections.Counter(a for a,_ in v).values())/len(v), 'pred 2/3 within1', np.mean([abs(a-2.5)<=1.5 for a,_ in v]))
print(collections.Counter(b for a,b in v))
# event -> stage
def ev2stage(e):
    i=round(e*6)
    return {0:1,1:1,2:2,3:2,4:3,5:3,6:4}[i]
v=[(z['stage_first'],ev2stage(z['ev'])) for z in X if z['stage_first'] and z['ev'] is not None]
print('ev->stage exact',np.mean([a==b for a,b in v]),'within1',np.mean([abs(a-b)<=1 for a,b in v]))
print(collections.Counter(round(z['ev']*6) for z in X if z['ev'] is not None))
print('n_docs dist', collections.Counter(z['n_docs'] for z in X).most_common(10))
print('n_all dist', collections.Counter(z['n_all'] for z in X).most_common(10))
