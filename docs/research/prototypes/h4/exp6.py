import exp5
from exp5 import *
obsc0 = [{**n, 'log_gh_repos_12m': 0.0, 'log_hn_12m': 0.0} for n in obsc]
exp5.obsc[:] = obsc0
print('--- non-software scenario: gh=0, hn=0 for every candidate')
sim('A0 baseline', F)
sim('B constrained all (keeps gh)', F, constrained=True)
sim('B2 constrained no gh/hn', nog, constrained=True)
sim('B2 + C=0.1', nog, constrained=True)
