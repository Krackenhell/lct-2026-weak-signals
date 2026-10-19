import os
import json, re, collections, sys
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
R='/home/user/lct-2026-weak-signals/backend/'
d=json.load(open(R+'data/seed/weak_signals_2026.json'))
def lvl(t):
    t=t.lower()
    if 'концеп' in t or t.strip().startswith('исслед'): return 1
    if 'прототип' in t or 'poc' in t: return 2
    if 'пилот' in t: return 3
    if 'внедрен' in t or 'серия' in t or 'поставк' in t: return 4
    return None
def gold(s): return lvl(re.split(r'→|/ |\(|,', s)[0])
T=[ (4, r'\bdeploy(s|ed|ment)\b|\bin production\b|\bcustomers?\b|\bcommercial(ly)? (available|launch|release)|\bgeneral availability\b|\bmass production|\bships?\b|\bshipping\b|\brolls? out\b|\badopt(s|ed|ion)\b|\bbanks? (use|adopt)'),
    (3, r'\bpilot|\btrial|\bfield test|\btestbed|\bproof of concept\b|\bpoc\b|\bcontrolled availability|\bbeta\b|\bphase (ii|2)\b'),
    (2, r'\bprototype|\bdemo(nstrat\w*)?\b|\bunveil|\blaunch(es|ed)?\b|\bintroduc|\breleas|\bopen[- ]source|\bannounc|\bpreview\b|\bphase (i|1)\b|\bgrant\b'),
    (1, r'arxiv|\bpaper\b|\bstudy\b|\bresearch|\bresearchers\b|\bpreprint|\bnature\b|\bscience\b|\bdoi\b'),
]
FUND=re.compile(r'\braise[sd]?\b|\bseries [a-e]\b|\bseed\b|\bfunding\b|\$\d|\bvaluation|\bacqui', re.I)
def typ(text):
    for lv,p in T:
        if re.search(p,text,re.I): return lv
    return None
res=[]
for x in d:
    g=gold(x['stage'])
    texts=[s['title']+' '+s['url'] for s in x['sources']]
    lvls=[typ(t) for t in texts]
    lvls=[l for l in lvls if l]
    fund=any(FUND.search(t) for t in texts)
    pred=max(lvls) if lvls else None
    res.append((g,pred,fund))
import numpy as np
def ev(name,f):
    p=[f(g,pr,fu) for g,pr,fu in res]
    ex=np.mean([a==b for (a,_,_),b in zip(res,p)]); w1=np.mean([abs(a-b)<=1 for (a,_,_),b in zip(res,p)])
    print(f'{name}: exact {ex:.2f} within1 {w1:.2f}', collections.Counter(p))
ev('ladder (none->2)', lambda g,p,f: p or 2)
ev('ladder, funding w/o stage ->3', lambda g,p,f: p or (3 if f else 2))
ev('const 2', lambda g,p,f: 2)
ev('const 3', lambda g,p,f: 3)
print('coverage (any typed event):', sum(1 for g,p,f in res if p)/len(res), 'funding titles', sum(f for *_,f in res))
print(collections.Counter((g,p) for g,p,f in res))
