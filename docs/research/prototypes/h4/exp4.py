from exp import *
logv = [x['response']['answers'] for x in dm]
def live_offsets(name, feats, **kw):
    X, y = T._matrix(rows, feats)
    m = Model(X, y, feats, **kw)
    idx = {f: i for i, f in enumerate(feats)}
    offs = []
    for a in logv:
        x = m.mu.copy()
        for f in feats:
            if f in ANSWERS and f in a: x[idx[f]] = a[f]['value']
        z = np.clip((x - m.mu) / m.sd, -3, 3)
        offs.append(float(z @ m.w))
    offs = np.array(offs)
    per = {}
    for f in ('independent', 'hype', 'early_stage', 'market_leaders', 'specific_tech'):
        if f in idx:
            i = idx[f]; v = np.array([a[f]['value'] for a in logv if f in a])
            per[f] = round(float(np.mean(np.clip((v - m.mu[i]) / m.sd[i], -3, 3) * m.w[i])), 2)
    print(f"{name:42s} live answer offset: mean {offs.mean():+.2f} sd {offs.std():.2f} |off|>2: {np.mean(np.abs(offs)>2):.0%} range [{offs.min():+.1f},{offs.max():+.1f}] per-feature {per}")
F = list(FEATURES)
nog = [f for f in F if f not in ('log_gh_repos_12m', 'log_hn_12m')]
live_offsets('A0 baseline', F)
live_offsets('B2 constrained no gh/hn', nog, constrained=True)
live_offsets('B2 + drop hype', [f for f in nog if f != 'hype'], constrained=True)
live_offsets('B2 + floor 0.15', nog, constrained=True, floor=0.15)
live_offsets('B2 + floor 0.2', nog, constrained=True, floor=0.2)
evaluate('B2 + drop hype', [f for f in nog if f != 'hype'], constrained=True)
evaluate('B2 + floor 0.15', nog, constrained=True, floor=0.15)
