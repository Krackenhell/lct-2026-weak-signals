import json, math, sys, statistics as st
sys.path.insert(0,'/home/user/lct-2026-weak-signals/backend')
from app.ml.model import SignalModel
from pathlib import Path
B='/home/user/lct-2026-weak-signals/backend/data/'
m=SignalModel.load(Path(B+'model/signal_model.json'))
rows=json.load(open(B+'model/training_rows.json'))
used=[r for r in rows if r['numeric']['log_total_works']>0]
neg=[math.expm1(r['numeric']['log_total_works']) for r in used if r['label']==0]
pos=[math.expm1(r['numeric']['log_total_works']) for r in used if r['label']==1]
print('neg works median', st.median(neg), 'neg<500:', sum(1 for w in neg if w<500), '/', len(neg), ' neg<100:', sum(1 for w in neg if w<100))
print('pos works median', st.median(pos), 'pos<500:', sum(1 for w in pos if w<500), '/', len(pos))
print('sum|coef|', sum(abs(c) for c in m.coef), 'max logit', m.intercept+3*sum(abs(c) for c in m.coef))
def show(name, x):
    p=m.predict(x); ex=m.explain(x)
    print(f'--- {name}: p={p:.4f} logit={m.logit(x):.2f}')
    for e in ex[:8]: print('    %-18s val=%7.3f contrib=%+.2f'%(e['feature'],e['value'],e['contribution']))
log=json.load(open(B+'log3.json'))
dm=[x for x in log if 'вопросы' in (x.get('purpose') or '') and x['ok']]
live_ans={a: st.mean([x['response']['answers'][a]['value'] for x in dm if a in x['response']['answers']]) for a in ['specific_tech','mass_adoption','market_leaders','standard','early_stage','independent','hype','novelty','benefit','maturity']}
live_ans.update(textbook=0.5, event=0.5)   # absent in sept live log -> answer_features default 0.5
obscure={'log_total_works':math.log1p(30),'recent_share':0.8,'growth':1.0,'age_years':3,'wiki_exists':0,'log_wiki_views':0,'log_gh_repos_12m':0,'log_hn_12m':0,'fresh_preprints':0.2,'share_science':1.0,'log_evidence':math.log1p(8)}
show('obscure academic phrase + avg live Jev answers', {**obscure, **live_ans})
neutral={a:0.5 for a in live_ans}
show('obscure phrase + all Jev answers 0.5 (no information)', {**obscure, **neutral})
mean_num={f:mu for f,mu in zip(m.features,m.mean) if f in obscure}
show('OpenAlex failed (means) + gh0 + avg live Jev', {**obscure, **{k:mean_num[k] for k in ('log_total_works','recent_share','growth','age_years')}, **live_ans})
# effect of independent
for v in (0.25,0.5,0.7,0.85,0.94):
    x={**obscure, **live_ans, 'independent':v}
    print('independent=%.2f -> p=%.4f'%(v, m.predict(x)))
for v in (0.0,0.17,0.5,1.0):
    x={**obscure, **live_ans, 'event':v}
    print('event=%.2f -> p=%.4f'%(v, m.predict(x)))
# live log3: compute answer-only logit part and how often independent clipped gives >+2
contrib_ind=[]
for x in dm:
    a=x['response']['answers']
    if 'independent' in a:
        z=max(-3,min(3,(a['independent']['value']-m.mean[m.features.index('independent')])/m.scale[m.features.index('independent')]))
        contrib_ind.append(z*m.coef[m.features.index('independent')])
print('independent contribution in Sept live Jev answers: mean %+.2f, >= +1: %d/%d, >= +2: %d'%(st.mean(contrib_ind), sum(c>=1 for c in contrib_ind), len(contrib_ind), sum(c>=2 for c in contrib_ind)))
