import json,re,sys
B='/home/user/lct-2026-weak-signals/backend/'
items=json.load(open(B+'data/seed/weak_signals_2026.json'))
terms=json.load(open(B+'data/seed/positive_terms.json'))
def W(s): return {w.rstrip('s') for w in re.findall(r'[a-z0-9]{3,}', s.lower())}
def best(name, dom):
    cw=W(name); b=(0,None)
    for it in items:
        if dom and it['domain']!=dom: continue
        for t in terms[str(it['id'])]:
            tw=W(t)
            j=len(cw&tw)/max(len(cw|tw),1)
            if j>b[0]: b=(j,t)
    return b
for fn in sys.argv[1:]:
    d=json.load(open(B+'data/model/'+fn))
    print('#########',fn)
    for r in d['runs']:
        if r['mode']!='только обнаружение': continue
        if r['status']!='done': print('  --',r['query'],r['status']); continue
        print('==',r['domain'],'|',r['query'],'| sec',r['seconds'],'| n',r['n_signals'],'| hits',r.get('dataset_hits_in_top15'),'| excl',r.get('exclusions'),'| watch',r.get('watch'),'| pp',r.get('passport'))
        for t in r['top']:
            j,bt=best(t['name'], r['domain'])
            print('   %2s p=%.3f %s %-55s ~ %.2f %s'%(t['rank'],t['p'],t.get('passport'),t['name'][:55],j,bt if j>=0.2 else ''))
