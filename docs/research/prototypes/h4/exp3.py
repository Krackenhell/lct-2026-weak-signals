import json, sys, warnings, numpy as np
warnings.filterwarnings('ignore')
sys.path.insert(0, '/home/user/lct-2026-weak-signals/backend')
from app.ml import train as T
from app.pipeline.features import FEATURES
rows = [r for r in json.load(open('/home/user/lct-2026-weak-signals/backend/data/model/training_rows.json')) if not r.get('incomplete') and T.has_evidence(r)]
for name, ex in [('baseline', set()), ('drop5', {'independent', 'early_stage', 'benefit', 'log_gh_repos_12m', 'log_hn_12m'}), ('drop3 (ind,gh,hn)', {'independent', 'log_gh_repos_12m', 'log_hn_12m'})]:
    feats = [f for f in T._usable(rows, FEATURES) if f not in ex]
    X, y = T._matrix(rows, feats)
    oof = T._oof(X, y)
    m = T._metrics(y, oof); ci = T._bootstrap_ci(y, oof, 500); rep = T._repeated(X, y)
    print(f"{name:20s} (train.py protocol, no eval clip) cv5 {m} f1ci {ci['f1']} rep {rep} n_feats {len(feats)}")
