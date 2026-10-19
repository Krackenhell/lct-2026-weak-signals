import json, math, numpy as np, sys
sys.path.insert(0, '/home/user/lct-2026-weak-signals/backend')
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
rows = json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/training_rows.json'))
m = json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/metrics.json'))
feats = m['features_used']
used = [r for r in rows if not r.get('incomplete') and r['numeric']['log_total_works'] > 0]
def vec(r): d = {**r['numeric'], **r['answers']}; return [d.get(f, 0.5) for f in feats]
X = np.array([vec(r) for r in used]); y = np.array([r['label'] for r in used])
pos = X[y == 1]
fi = {f: i for i, f in enumerate(feats)}
print('positives with gh=0 & hn=0:', int(((pos[:, fi['log_gh_repos_12m']] == 0) & (pos[:, fi['log_hn_12m']] == 0)).sum()), 'of', len(pos))
print('positives with gh=0:', int((pos[:, fi['log_gh_repos_12m']] == 0).sum()))
def fit(X, y):
    sc = StandardScaler().fit(X); c = LogisticRegression(C=0.5, max_iter=2000, class_weight='balanced').fit(sc.transform(X), y); return sc, c
sc, c = fit(X, y)
# synthetic niche junk: positive-like profile, purely academic
rng = np.random.default_rng(0)
def niche(n, jev_shift=0.0):
    idx = rng.integers(0, len(pos), n); Z = pos[idx].copy()
    Z[:, fi['log_gh_repos_12m']] = 0; Z[:, fi['log_hn_12m']] = 0; Z[:, fi['share_science']] = 1.0; Z[:, fi['wiki_exists']] = 0; Z[:, fi['log_wiki_views']] = 0
    Z[:, fi['log_total_works']] = np.log1p(rng.integers(5, 300, n))
    for f, s in [('novelty', -jev_shift), ('maturity', jev_shift), ('textbook', jev_shift), ('specific_tech', 0)]:
        Z[:, fi[f]] = np.clip(Z[:, fi[f]] + s, 0, 1)
    return Z
for shift in (0.0, 0.15, 0.3):
    tr = niche(50, shift); te = niche(15, shift)
    p0 = c.predict_proba(sc.transform(te))[:, 1]
    X2 = np.vstack([X, tr]); y2 = np.r_[y, np.zeros(50, int)]
    # OOF recall on real positives with augmented set
    oof = np.zeros(len(y2))
    for s in range(5):
        for a, b in StratifiedKFold(5, shuffle=True, random_state=s).split(X2, y2):
            s2, c2 = fit(X2[a], y2[a]); oof[b] += c2.predict_proba(s2.transform(X2[b]))[:, 1] / 5
    s2, c2 = fit(X2, y2)
    p1 = c2.predict_proba(s2.transform(te))[:, 1]
    rp = oof[:len(y)][y == 1]
    sciposmask = (pos[:, fi['log_gh_repos_12m']] == 0)
    print(f'jev_shift={shift}: heldout junk p<0.5 before {int((p0<0.5).sum())}/15 (median {np.median(p0):.3f}) after {int((p1<0.5).sum())}/15 (median {np.median(p1):.3f}); '
          f'real-pos OOF recall {np.mean(rp>=0.5):.2f}; gh=0 positives recall {np.mean(rp[sciposmask]>=0.5):.2f}; real-neg FPR {np.mean(oof[:len(y)][y==0]>=0.5):.3f}')
    w = dict(zip(feats, c2.coef_[0])); print('   weights gh %.2f hn %.2f share_sci %.2f novelty %.2f maturity %.2f works %.2f' % (w['log_gh_repos_12m'], w['log_hn_12m'], w['share_science'], w['novelty'], w['maturity'], w['log_total_works']))
