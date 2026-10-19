import json, sys, numpy as np
sys.path.insert(0, '/home/user/lct-2026-weak-signals/backend')
from app.ml import train as T
from app.pipeline.features import FEATURES
from scipy.optimize import minimize
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import roc_auc_score, f1_score, brier_score_loss, precision_score, recall_score

rows = json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/training_rows.json'))
rows = [r for r in rows if not r.get('incomplete') and T.has_evidence(r)]
feats = T._usable(rows, FEATURES)
X, y = T._matrix(rows, feats)
SIGN = {"log_total_works": -1, "recent_share": 1, "growth": 1, "age_years": -1, "wiki_exists": -1, "log_wiki_views": -1,
        "fresh_preprints": 1, "share_science": 1, "specific_tech": 1, "mass_adoption": -1, "market_leaders": -1, "standard": -1,
        "early_stage": 1, "independent": 1, "hype": -1, "novelty": 1, "benefit": 1, "textbook": -1, "maturity": -1, "event": 1}

def fit(Xs, y, C=0.5, constrained=True):
    n, d = Xs.shape
    w_pos = len(y) / (2 * y.sum()); w_neg = len(y) / (2 * (len(y) - y.sum()))
    sw = np.where(y == 1, w_pos, w_neg)
    def loss(theta):
        w, b = theta[:d], theta[d]
        z = Xs @ w + b
        p = 1 / (1 + np.exp(-z))
        l = np.sum(sw * (np.logaddexp(0, z) - y * z)) + 0.5 / C * np.sum(w ** 2)
        g = Xs.T @ (sw * (p - y)) + w / C
        gb = np.sum(sw * (p - y))
        return l, np.append(g, gb)
    bounds = []
    for f in feats:
        s = SIGN.get(f, 0) if constrained else 0
        bounds.append((0, None) if s > 0 else (None, 0) if s < 0 else (None, None))
    bounds.append((None, None))
    r = minimize(loss, np.zeros(d + 1), jac=True, method='L-BFGS-B', bounds=bounds)
    return r.x[:d], r.x[d]

def oof(constrained, seed=42):
    o = np.zeros(len(y))
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
        sc = StandardScaler().fit(X[tr])
        w, b = fit(sc.transform(X[tr]), y[tr], constrained=constrained)
        o[te] = 1 / (1 + np.exp(-(np.clip(sc.transform(X[te]), -3, 3) @ w + b)))
    return o

for c in (False, True):
    f1s, aucs, briers = [], [], []
    for seed in range(10):
        o = oof(c, seed)
        pr = (o >= 0.5).astype(int)
        f1s.append(f1_score(y, pr)); aucs.append(roc_auc_score(y, o)); briers.append(brier_score_loss(y, o))
    print('constrained' if c else 'free', 'F1 %.3f±%.3f AUC %.3f Brier %.3f' % (np.mean(f1s), np.std(f1s), np.mean(aucs), np.mean(briers)))
sc = StandardScaler().fit(X)
for c in (False, True):
    w, b = fit(sc.transform(X), y, constrained=c)
    print('constrained' if c else 'free', 'intercept', round(b, 2))
    print('   ', ', '.join(f'{f}={wi:+.2f}' for f, wi in zip(feats, w)))
