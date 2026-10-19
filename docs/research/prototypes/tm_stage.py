import runpy, sys, io, contextlib, numpy as np
sys.argv=["x", sys.argv[1]]
with contextlib.redirect_stdout(io.StringIO()):
    g=runpy.run_path("tm_emergence.py")
rows,y=g["rows"],g["y"]
def stage(f):
    gr, ac = f["growth2"], f["accel"]
    if f["log_works_total"] < 1.0: return "0 nascent(<2 works)"
    if gr > 0.3 and ac > 0: return "1 accelerating"
    if gr > 0.3: return "2 growing, decelerating"
    if gr > -0.1: return "3 plateau"
    return "4 declining"
st=np.array([stage(r["features"]) for r in rows])
for s in sorted(set(st)):
    m=st==s; print(f"{s:28s} n={m.sum():3d} became mainstream={y[m].mean():.2f}")
