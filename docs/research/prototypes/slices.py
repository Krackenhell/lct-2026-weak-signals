import json, numpy as np, collections
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
rows = json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/training_rows.json'))
neg = json.load(open('/home/user/lct-2026-weak-signals/backend/data/seed/negatives.json'))['items']
hard = {f'neg-{i}': bool(n.get('hard')) for i, n in enumerate(neg)}
feats = json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/metrics.json'))['features_used']
used = [r for r in rows if not r.get('incomplete') and r['numeric']['log_total_works'] > 0]
X = np.array([[{**r['numeric'], **r['answers']}.get(f, 0.5) for f in feats] for r in used]); y = np.array([r['label'] for r in used])
oof = np.zeros(len(y))
for s in range(10):
    for a, b in StratifiedKFold(5, shuffle=True, random_state=s).split(X, y):
        sc = StandardScaler().fit(X[a]); c = LogisticRegression(C=0.5, max_iter=2000, class_weight='balanced').fit(sc.transform(X[a]), y[a])
        oof[b] += c.predict_proba(sc.transform(X[b]))[:, 1] / 10
sl = collections.defaultdict(list)
for r, p in zip(used, oof):
    if r['label'] == 0:
        sl[r['code']].append(p); sl['hard' if hard.get(r['key']) else 'not_hard'].append(p)
        if r['numeric']['log_total_works'] < np.log1p(300): sl['works<300'].append(p)
for k, v in sl.items():
    v = np.array(v); print(f'{k:10s} n={len(v):3d} false-signal(p>=0.5)={np.mean(v>=0.5):.3f} p>=0.9: {int((v>=0.9).sum())}')
pp = oof[y == 1]; print('pos recall', np.mean(pp >= 0.5), 'share p>=0.99', np.mean(pp >= 0.99))
print('share of all OOF p>=0.99', np.mean(oof >= 0.99))
