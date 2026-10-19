import os
"""Exp C: semantic duplicates in saved top lists vs the word-Jaccard near_duplicate().
Exp D: semantic matching of top lists to organizer dataset vs strict word matching (eval_live.matches).
Exp E: agreement of embedding relevance with Jev relevance on September fintech runs (r1/run3/run4).
"""
import itertools
import json
import re
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts") if os.path.basename(os.path.dirname(os.path.abspath(__file__))) != "scripts" else os.path.dirname(os.path.abspath(__file__)))
from emb import Embedder  # noqa: E402

B = "/home/user/lct-2026-weak-signals/backend/"
LINK = {"in", "on", "of", "for", "the", "and", "a", "an", "based", "driven", "enabled"}


def key_words(name):  # copy of decide._key_words
    words = re.findall(r"[a-zа-яё0-9]+", name.lower().replace("-", " "))
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words if w not in LINK}


def near_duplicate(a, b):  # copy of decide.near_duplicate
    wa, wb = key_words(a), key_words(b)
    return bool(wa and wb) and len(wa & wb) / len(wa | wb) >= 0.6


def _words(s):  # copy of eval_live._words
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]{3,}", s.lower())}


def strict(c, ts):
    cw = _words(c)
    return any(_words(t) and len(cw & _words(t)) / len(_words(t) | cw) >= 0.5 for t in ts)


e = Embedder(max_len=48)
runs = []
for f in ("live_eval.json", "live_eval_science_only.json", "live_eval_before.json"):
    for r in json.load(open(B + "data/model/" + f))["runs"]:
        if r["top"]:
            runs.append((f, r))

print("=== Exp C: duplicate pairs inside one top list (cos >= 0.75) ===")
for f, r in runs:
    names = [t["name"] for t in r["top"]]
    V = e.encode(names)
    for i, j in itertools.combinations(range(len(names)), 2):
        c = float(V[i] @ V[j])
        if c >= 0.75:
            print(f"  [{f[:22]:22s}|{r['query'][:18]:18s}] cos={c:.2f} jaccard_dup={near_duplicate(names[i], names[j])!s:5s} {names[i]!r} ~ {names[j]!r}")

print("\n=== Exp D: semantic vs strict match to organizer dataset ===")
items = json.load(open(B + "data/seed/weak_signals_2026.json"))
terms = json.load(open(B + "data/seed/positive_terms.json"))
DOM = {"перспективные решения в финтехе": "Финтех", "слабые сигналы в кибербезопасности ИИ": "Защита ИИ", "робототехника": "Роботы",
       "edge AI и вычисления на устройствах": "Edge", "инфраструктура для ИИ": "Инфраструктура ИИ", "индустриальный ИИ": "Индустриальный ИИ"}
for f, r in runs:
    if r["query"] not in DOM or r.get("mode") != "только обнаружение":
        continue
    dom = [it for it in items if it["domain"] == DOM[r["query"]]]
    names = [t["name"] for t in r["top"]]
    V = e.encode(names)
    strict_hits, sem_hits = set(), {}
    for it in dom:
        ts = terms[str(it["id"])]
        T = e.encode(ts + [it["name"]])  # english terms + russian description (MiniLM is weak on RU; kept for completeness)
        for n, v in zip(names, V):
            if strict(n, ts):
                strict_hits.add(it["id"])
            s = float((T[: len(ts)] @ v).max())
            if s >= 0.70:
                sem_hits.setdefault(it["id"], []).append((round(s, 2), n, ts[0]))
    extra = {k: v for k, v in sem_hits.items() if k not in strict_hits}
    print(f"  [{f[:22]:22s}|{r['query'][:22]:22s}] strict={len(strict_hits)} semantic>=0.70={len(set(sem_hits) | strict_hits)}")
    for k, v in extra.items():
        print(f"      +{k}: {v}")

print("\n=== Exp E: embedding relevance vs Jev relevance (fintech, Sept runs with Jev) ===")
q = e.encode(["Financial technology: new ways to pay, lend, bank, invest, insure and comply with financial regulation using software, cryptography and AI."])[0]
allc = []
for fn in ("r1.json", "run3.json", "run4.json"):
    d = json.load(open(B + "data/" + fn))
    for c in d["signals"] + d["excluded"]:
        if c.get("relevance") is not None:
            allc.append((c["name"], c["relevance"], c.get("exclusion_code"), c.get("origin")))
names = [c[0] for c in allc]
s = e.encode(names) @ q
jev = np.array([c[1] for c in allc])
irr = np.array([c[2] == "irrelevant" for c in allc])
print(f"  candidates={len(allc)} spearman-like corr(emb, jev)={np.corrcoef(np.argsort(np.argsort(s)), np.argsort(np.argsort(jev)))[0,1]:.2f}")
if irr.any():
    print(f"  AUC of (−emb score) for Jev-'irrelevant' exclusions: {roc_auc_score(irr, -s):.2f} (n_irrelevant={irr.sum()})")
for (n, j, code, origin), v in sorted(zip(allc, s), key=lambda x: x[1])[:12]:
    print(f"     emb={v:.2f} jev={j:.2f} {code or 'signal':16s} {n}")
