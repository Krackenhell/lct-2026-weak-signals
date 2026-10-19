import runpy, sys, io, contextlib, numpy as np
sys.argv=["x", sys.argv[1]]
with contextlib.redirect_stdout(io.StringIO()):
    g=runpy.run_path("tm_emergence.py")
rows,y=g["rows"],g["y"]
q=np.array([r["ind"]["yoon_quadrant"] for r in rows])
for thr in (0.0,0.25,0.5):
    m=q>thr; print(f"KEM weak-signal quadrant (pct_growth - pct_visibility > {thr}): n={m.sum()}, share became mainstream={y[m].mean():.2f} vs rest {y[~m].mean():.2f}")
print("base rate", y.mean().round(2))
