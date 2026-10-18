from exp import *
import numpy as np
rng = np.random.default_rng(0)
print('live Sept avg answers:', {k: round(v, 2) for k, v in live.items()})
def drift(name, feats, **kw):
    X, y = T._matrix(rows, feats)
    ans_idx = [i for i, f in enumerate(feats) if f in ANSWERS]
    flips, dl, recs, precs = [], [], [], []
    for seed in range(5):
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            m = Model(X[tr], y[tr], feats, **kw)
            p0 = m.p(X[te])
            Xd = X[te].copy()
            Xd[:, ans_idx] = np.clip(Xd[:, ans_idx] + rng.normal(0, 0.1, (len(te), len(ans_idx))), 0, 1)
            p1 = m.p(Xd)
            l0, l1 = np.log(p0 / (1 - p0 + 1e-12) + 1e-12), np.log(p1 / (1 - p1 + 1e-12) + 1e-12)
            flips.append(((p0 >= .5) != (p1 >= .5)).mean()); dl.append(np.abs(l1 - l0).mean())
    o = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=42).split(X, y):
        o[te] = Model(X[tr], y[tr], feats, **kw).p(X[te])
    m = Model(X, y, feats, **kw)
    signs = {f: round(w, 2) for f, w in zip(feats, m.w) if abs(w) > 0.05}
    print(f"{name:40s} prec {precision_score(y, o>=.5):.3f} rec {recall_score(y, o>=.5):.3f} | answer-noise(sd .1): flips {np.mean(flips):.3f} mean|dlogit| {np.mean(dl):.2f} | max|logit| span {m.b:+.2f} sum|w|*3={3*np.abs(m.w).sum():.1f}")
    return signs
F = list(FEATURES)
drop5 = [f for f in F if f not in ('independent', 'early_stage', 'benefit', 'log_gh_repos_12m', 'log_hn_12m')]
for name, feats, kw in [('A0 baseline', F, {}), ('A1 drop independent', noind, {}), ('A2 drop ind+gh+hn', nogh, {}),
                        ('A3 drop ind,early,benefit,gh,hn', drop5, {}), ('B2 constrained no gh/hn', [f for f in F if f not in ('log_gh_repos_12m','log_hn_12m')], {'constrained': True}),
                        ('B constrained all', F, {'constrained': True})]:
    s = drift(name, feats, **kw)
    if name.startswith(('A3', 'B2')): print('    weights', s)
evaluate('A3 drop ind,early,benefit,gh,hn (sklearn-equiv)', drop5)
evaluate('A3 + unweighted', drop5, balanced=False)
evaluate('A3 + clip at train', drop5, clip_train=True)
