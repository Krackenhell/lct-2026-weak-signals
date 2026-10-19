import json, sys, math, warnings, statistics as st
import numpy as np
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/lct-2026-weak-signals/backend')
from app.ml import train as T
from app.pipeline.features import FEATURES, ANSWERS, NUMERIC
from scipy.optimize import minimize
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, brier_score_loss, precision_score, recall_score
B = '/home/user/lct-2026-weak-signals/backend/data/'
rows = [r for r in json.load(open(B + 'model/training_rows.json')) if not r.get('incomplete') and T.has_evidence(r)]
log = json.load(open(B + 'log3.json'))
dm = [x for x in log if 'вопросы' in (x.get('purpose') or '') and x['ok']]
live = {a: st.mean([x['response']['answers'][a]['value'] for x in dm if a in x['response']['answers']]) for a in ['specific_tech','mass_adoption','market_leaders','standard','early_stage','independent','hype','novelty','benefit','maturity']}
live.update(textbook=0.5, event=0.5)
SIGN = {"log_total_works": -1, "recent_share": 1, "growth": 1, "age_years": -1, "wiki_exists": -1, "log_wiki_views": -1,
        "fresh_preprints": 1, "share_science": 1, "specific_tech": 1, "mass_adoption": -1, "market_leaders": -1, "standard": -1,
        "early_stage": 1, "independent": 1, "hype": -1, "novelty": 1, "benefit": 1, "textbook": -1, "maturity": -1, "event": 1,
        "log_gh_repos_12m": -1, "log_hn_12m": -1}
obscure_num = {'log_total_works': math.log1p(30), 'recent_share': 0.8, 'growth': 1.0, 'age_years': 3, 'wiki_exists': 0, 'log_wiki_views': 0,
               'log_gh_repos_12m': 0, 'log_hn_12m': 0, 'fresh_preprints': 0.2, 'share_science': 1.0, 'log_evidence': math.log1p(8)}
neutral = {a: 0.5 for a in ANSWERS}
mature = {'log_total_works': math.log1p(20000), 'recent_share': 0.35, 'growth': 0.1, 'age_years': 25, 'wiki_exists': 1, 'log_wiki_views': math.log1p(8000),
          'log_gh_repos_12m': math.log1p(2000), 'log_hn_12m': math.log1p(40), 'fresh_preprints': 1.0, 'share_science': 0.8, 'log_evidence': math.log1p(15)}
mature_ans = {**live, 'maturity': 0.85, 'mass_adoption': 0.7, 'novelty': 0.15, 'textbook': 0.85}
market = {'log_total_works': 0.0, 'recent_share': 0.0, 'growth': 0.0, 'age_years': 0, 'wiki_exists': 0, 'log_wiki_views': 0,
          'log_gh_repos_12m': math.log1p(150), 'log_hn_12m': math.log1p(12), 'fresh_preprints': 0.0, 'share_science': 0.0, 'log_evidence': math.log1p(10)}
market_ans = {**live, 'novelty': 0.85, 'event': 0.8, 'maturity': 0.25}
PROFILES = {'obscure+live': {**obscure_num, **live}, 'obscure+0.5': {**obscure_num, **neutral}, 'mature': {**mature, **mature_ans}, 'market': {**market, **market_ans}}

def fit(Xs, y, feats, C=0.5, constrained=False, balanced=True):
    n, d = Xs.shape
    if balanced:
        sw = np.where(y == 1, len(y) / (2 * y.sum()), len(y) / (2 * (len(y) - y.sum())))
    else:
        sw = np.ones(len(y))
    def loss(theta):
        w, b = theta[:d], theta[d]
        z = Xs @ w + b
        p = 1 / (1 + np.exp(-z))
        l = np.sum(sw * (np.logaddexp(0, z) - y * z)) + 0.5 / C * np.sum(w ** 2)
        return l, np.append(Xs.T @ (sw * (p - y)) + w / C, np.sum(sw * (p - y)))
    bounds = [((0, None) if SIGN.get(f, 0) > 0 else (None, 0) if SIGN.get(f, 0) < 0 else (None, None)) if constrained else (None, None) for f in feats] + [(None, None)]
    r = minimize(loss, np.zeros(d + 1), jac=True, method='L-BFGS-B', bounds=bounds)
    return r.x[:d], r.x[d]

class Model:
    def __init__(self, X, y, feats, constrained=False, balanced=True, floor=0.0, clip_train=False, prior_shift=False):
        self.mu = X.mean(0); sd = X.std(0)
        self.sd = np.where([f in ANSWERS for f in feats], np.maximum(sd, floor), sd); self.sd[self.sd == 0] = 1
        Z = (X - self.mu) / self.sd
        if clip_train: Z = np.clip(Z, -3, 3)
        self.w, self.b = fit(Z, y, feats, constrained=constrained, balanced=balanced)
        if prior_shift and balanced:
            self.b -= math.log((len(y) - y.sum()) / y.sum())
    def p(self, X):
        return 1 / (1 + np.exp(-(np.clip((X - self.mu) / self.sd, -3, 3) @ self.w + self.b)))

def evaluate(name, feats, **kw):
    X, y = T._matrix(rows, feats)
    f1s, aucs, brs, hi = [], [], [], []
    for seed in range(10):
        o = np.zeros(len(y))
        for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
            m = Model(X[tr], y[tr], feats, **kw); o[te] = m.p(X[te])
        f1s.append(f1_score(y, o >= 0.5)); aucs.append(roc_auc_score(y, o)); brs.append(brier_score_loss(y, o)); hi.append((o >= 0.95).mean())
        if seed == 0: o0 = o
    # LODO
    lodo = {}
    for d in ['Защита ИИ', 'Роботы', 'Финтех', 'Инфраструктура ИИ']:
        tr = np.array([r['domain'] != d for r in rows]); te = ~tr
        m = Model(X[tr], y[tr], feats, **kw); p = m.p(X[te])
        lodo[d[:6]] = round(f1_score(y[te], p >= 0.5), 2)
    m = Model(X, y, feats, **kw)
    prof = {k: round(float(m.p(np.array([[v.get(f, 0.5) for f in feats]]))[0]), 3) for k, v in PROFILES.items()}
    pos_hi = (o0[y == 1] >= 0.75).mean()
    bad = [f for f, w in zip(feats, m.w) if SIGN.get(f, 0) * w < -1e-6]
    print(f"{name:42s} F1 {np.mean(f1s):.3f}±{np.std(f1s):.3f} AUC {np.mean(aucs):.3f} Brier {np.mean(brs):.3f} oof>=.95 {np.mean(hi):.2f} pos>=.75 {pos_hi:.2f} LODO {lodo} {prof} b={m.b:+.2f} inverted={bad}")
    return m

F = list(FEATURES)
noind = [f for f in F if f != 'independent']
nogh = [f for f in noind if f not in ('log_gh_repos_12m', 'log_hn_12m')]
if __name__ == '__main__':
    evaluate('A0 baseline (as deployed: balanced, no train clip)', F)
    evaluate('A1 drop independent', noind)
    evaluate('A2 drop independent+gh+hn', nogh)
    evaluate('B  constrained (all signs, incl gh/hn<=0)', F, constrained=True)
    evaluate('B2 constrained, no gh/hn', [f for f in F if f not in ('log_gh_repos_12m','log_hn_12m')], constrained=True)
    evaluate('C  constrained + prior shift', F, constrained=True, prior_shift=True)
    evaluate('C2 constrained no gh/hn + prior shift', [f for f in F if f not in ('log_gh_repos_12m','log_hn_12m')], constrained=True, prior_shift=True)
    evaluate('C3 constrained no gh/hn, unweighted', [f for f in F if f not in ('log_gh_repos_12m','log_hn_12m')], constrained=True, balanced=False)
    evaluate('D  floor sd answers 0.15', F, floor=0.15)
    evaluate('D2 floor 0.15, drop ind, no gh/hn', nogh, floor=0.15)
    evaluate('D3 floor 0.15, drop ind, no gh/hn, prior', nogh, floor=0.15, prior_shift=True)
    evaluate('D4 floor 0.2 constrained no gh/hn', [f for f in F if f not in ('log_gh_repos_12m','log_hn_12m')], floor=0.2, constrained=True)
