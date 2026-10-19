from exp import *
rng = np.random.default_rng(1)
logv = [x['response']['answers'] for x in dm]
obsc = [r['numeric'] for r in rows if r['numeric']['log_total_works'] < math.log1p(500)]
print('obscure numeric pool', len(obsc))
def sim(name, feats, **kw):
    X, y = T._matrix(rows, feats)
    m = Model(X, y, feats, **kw)
    hi, n05, top95 = [], [], []
    for _ in range(300):
        cands = []
        for a in rng.choice(len(logv), 30):
            num = obsc[rng.integers(len(obsc))]
            ans = {k: v['value'] for k, v in logv[a].items() if k in ANSWERS}
            x = {**num, **{k: 0.5 for k in ('textbook', 'event')}, **ans}
            cands.append(x)
        p = m.p(np.array([[c.get(f, 0.5) for f in feats] for c in cands]))
        ps = np.sort(p)[::-1]
        passing = ps[ps >= 0.5][:15]
        n05.append(len(passing)); top95.append((passing >= 0.95).mean() if len(passing) else 0)
    print(f"{name:34s} simulated live (30 cands, Sept answers x obscure numerics): n passing 0.5 in top15 {np.mean(n05):.1f}, share of shown with p>=0.95 {np.mean(top95):.0%}")
F = list(FEATURES); nog = [f for f in F if f not in ('log_gh_repos_12m', 'log_hn_12m')]
sim('A0 baseline', F)
sim('A1 drop independent', [f for f in F if f != 'independent'])
sim('B constrained all', F, constrained=True)
sim('B2 constrained no gh/hn', nog, constrained=True)
sim('B2 + prior shift', nog, constrained=True, prior_shift=True)
