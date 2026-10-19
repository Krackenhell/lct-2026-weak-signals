"""PoC: stage-level snapshot of `assessed` + deterministic offline re-decide of variants.
Runs the real pipeline offline (FakeWeb from tests, heuristic decision model, no LLM)."""
import os, sys, tempfile, json, asyncio, dataclasses
from pathlib import Path
_TMP = Path(tempfile.mkdtemp(prefix="ws-proto-"))
os.environ.update(DATABASE_URL=f"sqlite:///{_TMP/'t.db'}", CACHE_DIR=str(_TMP/"cache"), DECISION_PROVIDER="heuristic", LLM_PROVIDER="none",
                  TYPESAFE_API_KEY="", GIGACHAT_AUTH_KEY="", OPENALEX_API_KEY="", GITHUB_TOKEN="", CHECK_LINKS="false", S2_API_KEY="")
sys.path.insert(0, "/home/user/lct-2026-weak-signals/backend")
from app.config import get_settings; get_settings.cache_clear()
from app.db import init_db, SessionLocal; init_db()
from app.models import Run, Candidate
from app.pipeline import runner, decide as decide_mod
from app.pipeline.evidence import Evidence
from app.collectors.base import RawDoc
from app.decision.base import DecisionResult
from app.ml.model import SignalModel
from tests.fakes import FakeWeb

SNAP = _TMP / "snap.json"

def dump_assessed(assessed):
    def ser(a):
        return {"c": {**a["c"], "methods": list(a["c"]["methods"])},
                "ev": {**dataclasses.asdict(a["ev"]), "docs": [dataclasses.asdict(d) for d in a["ev"].docs]},
                "answers": a["res"].answers, "res_ok": a["res"].ok, "provider": a["res"].provider,
                "features": a["features"], "prob": a["prob"], "missing": a.get("missing", []), "passport": a["passport"], "items": a["items"]}
    SNAP.write_text(json.dumps([ser(a) for a in assessed], ensure_ascii=False, default=str))

def load_assessed(path):
    out = []
    for r in json.loads(Path(path).read_text()):
        ev = Evidence(**{**r["ev"], "docs": [RawDoc(**d) for d in r["ev"]["docs"]]})
        out.append({"c": r["c"], "ev": ev, "res": DecisionResult(r["answers"], r["provider"], "", 0, ok=r["res_ok"]),
                    "features": r["features"], "prob": r["prob"], "missing": r["missing"], "passport": r["passport"], "items": r["items"]})
    return out

real_decide = runner.decide
def capturing_decide(assessed, model, top_k):
    dump_assessed(assessed)
    return real_decide(assessed, model, top_k)
runner.decide = capturing_decide
runner.HttpClient = FakeWeb().client
async def no_links(urls, **_): return {u: "ok" for u in urls}
runner.links_mod.check_all = no_links

with SessionLocal() as s:
    run = Run(query="edge AI", options={}); s.add(run); s.commit(); rid = run.id
asyncio.run(runner.execute(rid))
with SessionLocal() as s:
    live = {c.name: (c.status, c.rank, c.exclusion_code) for c in s.query(Candidate).filter_by(run_id=rid)}
print("live run:", rid, "candidates", len(live), "signals", sum(v[0] == "signal" for v in live.values()), "snapshot bytes", SNAP.stat().st_size)

model = SignalModel.load()
A = load_assessed(SNAP)
replayed = real_decide(A, model, get_settings().top_k)
same = all((d["status"], d.get("rank"), d.get("code")) == live[a["c"]["name_en"]] for a, d in zip(A, replayed))
print("re-decide reproduces live decisions exactly:", same)
# Variant: stricter theme cap and relevance gate — compare tops
decide_mod.MAX_PER_THEME = 2
var = real_decide(load_assessed(SNAP), model, get_settings().top_k)
base_top = [a["c"]["name_en"] for a, d in sorted(zip(A, replayed), key=lambda x: x[1].get("rank") or 99) if d["status"] == "signal"]
var_top = [a["c"]["name_en"] for a, d in sorted(zip(A, var), key=lambda x: x[1].get("rank") or 99) if d["status"] == "signal"]
print("baseline top:", base_top); print("variant top :", var_top)
print("diff to judge: added", sorted(set(var_top) - set(base_top)), "removed", sorted(set(base_top) - set(var_top)))
