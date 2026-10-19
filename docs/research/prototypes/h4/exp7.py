import exp
from exp5 import *
_orig = exp.fit
for C in (0.5, 0.1, 0.05):
    exp.fit = lambda Xs, y, feats, C_=C, **k: _orig(Xs, y, feats, C=C_, **{kk: v for kk, v in k.items() if kk != 'C'})
    import exp5 as e5
    e5.fit = exp.fit
    exp.Model.__init__.__globals__['fit'] = exp.fit
    sim(f'B2 C={C}', nog, constrained=True)
    evaluate(f'B2 C={C}', nog, constrained=True)
