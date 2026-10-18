import sys, re, json
sys.path.insert(0, "/home/user/lct-2026-weak-signals/backend")
import app.pipeline.decide as D

DEDUP_DROP = {"all", "technology", "technologie", "technologies", "development", "system", "systems", "solution", "platform"}
def lemma(w):
    if len(w) > 4 and w.endswith("ies"): return w[:-3] + "y"
    if len(w) > 4 and w.endswith("s") and not w.endswith("ss"): return w[:-1]
    return w
def kw(name):
    name = re.sub(r"\([^)]*\)", " ", name)
    words = re.findall(r"[a-zа-яё0-9]+", name.lower().replace("-", " "))
    return {lemma(w) for w in words if w not in D._LINK_WORDS}
def near_dup(a, b):
    wa, wb = kw(a) - DEDUP_DROP, kw(b) - DEDUP_DROP
    if not wa or not wb: return False
    return len(wa & wb) / len(wa | wb) >= 0.6
def anchors(plan, query):
    out = set()
    if plan.get("generated_by") != "lexicon" and re.search(r"[a-z]", plan.get("topic_en", ""), re.I):
        out |= kw(plan["topic_en"])
    out |= kw(" ".join(re.findall(r"[A-Za-z][A-Za-z0-9\-]+", query)))
    head = plan.get("subqueries", [])[:6] if plan.get("generated_by") != "lexicon" else []
    if len(head) >= 3:
        from collections import Counter
        c = Counter(w for s in head for w in kw(s))
        out |= {w for w, n in c.items() if n >= len(head) / 2}
    return out - D._GENERIC_WORDS

def diversify(names, anch, topic, top_k=15, cap=3, lexicon=False):
    kept, themes, res = [], {}, {}
    for n in names:
        if topic and not lexicon and near_dup(n, topic):
            res[n] = "query_echo"; continue
        twin = next((k for k in kept if near_dup(n, k)), None)
        tw = {w for w in kw(n) - D._GENERIC_WORDS - anch if len(w) > 3}
        theme = None if lexicon else next((w for w in sorted(tw) if themes.get(w, 0) >= cap), None)
        if twin: res[n] = "duplicate:" + twin
        elif theme and len(kept) < top_k: res[n] = "crowded:" + theme
        else:
            kept.append(n); res[n] = "kept"
            for w in tw: themes[w] = themes.get(w, 0) + 1
    return kept, res

cases = {
 "graphene": (["multilayer graphene", "twisted bilayer graphene", "rhombohedral multilayer graphene", "CVD multilayer graphene growth", "graphene heterostructures",
   "few-layer graphene membranes", "graphene oxide membranes", "laser-induced graphene", "graphene-based supercapacitor electrodes",
   "moire superlattices", "intercalated multilayer graphene", "graphene thermal interface materials", "hexagonal boron nitride encapsulation"],
   {"topic_en": "Multilayer graphene technology", "subqueries": ["twisted multilayer graphene", "rhombohedral graphene", "graphene heterostructures", "CVD graphene growth", "graphene membranes", "laser induced graphene"], "generated_by": "gigachat"}, "технология многослойного графена"),
 "microfluidics": (["microfluidic chips", "droplet microfluidics", "digital microfluidics", "paper-based microfluidics", "inertial microfluidics",
   "organ-on-a-chip", "centrifugal microfluidics", "open microfluidics", "3D-printed microfluidic chips", "lab on a chip platforms"],
   {"topic_en": "Microfluidic chips", "subqueries": ["droplet microfluidics", "organ on chip", "paper based microfluidics", "digital microfluidics", "microfluidic biosensors", "3D printed microfluidic devices"], "generated_by": "gigachat"}, "микрофлюидные чипы"),
 "microfluidics_topic_miss": (["droplet microfluidics", "digital microfluidics", "paper-based microfluidics", "inertial microfluidics", "centrifugal microfluidics", "open microfluidics"],
   {"topic_en": "Lab-on-a-chip technologies", "subqueries": ["droplet microfluidics", "organ on chip", "paper based microfluidics", "digital microfluidics", "microfluidic biosensors", "point of care diagnostics"], "generated_by": "gigachat"}, "микрофлюидные чипы"),
 "ai_infra_18_10": (["Annealing-based Quantum Neural Networks", "Hybrid Quantum-Classical Optimization", "Quantum Kernel Support Vector Machines",
   "Generative Quantum Machine Learning", "Quantum Natural Language Processing", "Combinatorial Fusion", "Variational Quantum Algorithms", "tool learning", "Neural Network Representation Learning"],
   {"topic_en": "AI infrastructure", "subqueries": ["AI accelerators", "optical interconnects", "KV cache offloading", "quantum machine learning hardware", "CXL memory pooling", "liquid cooling datacenters"], "generated_by": "gigachat"}, "инфраструктура для ИИ"),
 "energy_18_10": (["solar-thermochemical water splitting", "all-solid-state batteries (ASSB)", "solid-state lithium-ion batteries", "NASICON solid electrolytes",
   "solid state battery", "flow-batteries", "wind-solar-hydrogen system integration", "distributed energy resource aggregation"],
   {"topic_en": "energy storage", "subqueries": ["solid state batteries", "sodium ion batteries", "flow batteries", "green hydrogen", "thermal storage", "virtual power plants"], "generated_by": "gigachat"}, "энергетика и накопители энергии"),
}
for k, (names, plan, q) in cases.items():
    a = anchors(plan, q)
    kept, res = diversify(names, a, plan["topic_en"])
    print("==", k, "anchors", sorted(a), "kept", len(kept), "of", len(names))
    for n, r in res.items():
        if r != "kept": print("    ", n, "->", r)
# live tops replay (no topic known -> use query-latin only) to show no regressions in count
for f in ["live_eval.json", "live_eval_science_only.json"]:
    d = json.load(open("/home/user/lct-2026-weak-signals/backend/data/model/" + f))
    for r in d["runs"]:
        if not r["top"]: continue
        names = [t["name"] for t in r["top"]]
        base = D.decide  # baseline diversity on names only
        kept, res = diversify(names, set(), "")
        changed = {n: v for n, v in res.items() if v != "kept"}
        print(f[:22], r["query"][:30], len(names), "->", len(kept), changed)
