import sys
sys.path.insert(0, "/home/user/lct-2026-weak-signals/backend")
from types import SimpleNamespace
from app.collectors.base import RawDoc
from app.pipeline.decide import decide, near_duplicate, PAPER_TITLE, _key_words

def cand(name, p=0.9):
    answers = {k: {"value": v} for k, v in {"relevance": 0.9, "specific_tech": 0.9, "is_technology": 0.9}.items()}
    ev = SimpleNamespace(docs=[RawDoc(url=f"https://arxiv.org/abs/{i}", title="t", source_name="arXiv", source_type="preprint", collector="arxiv") for i in range(4)])
    return {"c": {"name_en": name}, "res": SimpleNamespace(ok=True, answers=answers), "features": {}, "prob": p, "ev": ev, "passport": {"level": "B"}}

sets = {
 "graphene": ["twisted bilayer graphene", "rhombohedral multilayer graphene", "CVD multilayer graphene growth", "graphene heterostructures",
              "few-layer graphene membranes", "graphene oxide membranes", "laser-induced graphene", "graphene-based supercapacitor electrodes",
              "moire superlattices", "intercalated multilayer graphene", "graphene thermal interface materials", "hexagonal boron nitride encapsulation"],
 "microfluidics": ["droplet microfluidics", "digital microfluidics", "paper-based microfluidics", "inertial microfluidics",
                   "organ-on-a-chip", "centrifugal microfluidics", "open microfluidics", "3D-printed microfluidic chips",
                   "lab on a chip platforms", "organ on a chip devices"],
 "ai_infra_18_10": ["Annealing-based Quantum Neural Networks", "Hybrid Quantum-Classical Optimization", "Quantum Kernel Support Vector Machines",
   "Generative Quantum Machine Learning", "Quantum Natural Language Processing", "Combinatorial Fusion", "Variational Quantum Algorithms",
   "tool learning", "Neural Network Representation Learning"],
 "energy_18_10": ["solar-thermochemical water splitting", "all-solid-state batteries (ASSB)", "solid-state lithium-ion batteries", "NASICON solid electrolytes",
   "solid state battery", "flow-batteries", "wind-solar-hydrogen system integration", "distributed energy resource aggregation"],
}
for k, names in sets.items():
    out = decide([cand(n, 0.99 - i / 100) for i, n in enumerate(names)], None, 15)
    print("==", k, "kept", sum(d["status"] == "signal" for d in out), "of", len(names))
    for n, d in zip(names, out):
        if d["status"] != "signal":
            print("   ", n, "->", d.get("code"), "|", d.get("reason")[:80])
print(_key_words("all-solid-state batteries (ASSB)"), _key_words("solid state battery"))
for n in ["lab on a chip platforms", "organ on a chip devices", "lab-on-a-chip", "quantum computing as a service", "graphene on a substrate"]:
    print(n, bool(PAPER_TITLE.search(n)))
