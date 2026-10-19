import os
"""Exp F: per-cluster c-TF-IDF phrase extraction vs global document-frequency mining (discovery.mine_phrases).

Pseudo-corpus per domain = saved evidence docs of organizer signals + team negatives of that domain (~400 docs).
Metric: share of organizer signals (positives) whose term is matched (eval_live.matches rule) by at least one of
the 40 extracted phrases; also share of negatives matched (these are mature/broad themes we would rather not surface).
Also reports clustering agreement with the item each doc was retrieved for (ARI), as a sanity check.
"""
import json
import math
import re
import sys
from collections import Counter, defaultdict

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering
from sklearn.metrics import adjusted_rand_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts") if os.path.basename(os.path.dirname(os.path.abspath(__file__))) != "scripts" else os.path.dirname(os.path.abspath(__file__)))
from emb import Embedder  # noqa: E402

SP = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"
D = json.load(open(SP + "data/pseudo_corpus.json"))
STOP, GENERIC = set(D["stop"]), set(D["generic"])
JF, JA, JL = set(D["junk_first"]), set(D["junk_any"]), set(D["junk_last"])


def norm(name):
    s = re.sub(r"[^a-z0-9 ]", " ", name.lower())
    return " ".join(w[:-1] if len(w) > 4 and w.endswith("s") and not w.endswith("ss") else w for w in s.split())


def grams(text):
    toks = re.findall(r"[A-Za-z][A-Za-z0-9\-]+", text)
    out = {}
    for n in (2, 3, 4):
        for j in range(len(toks) - n + 1):
            g = toks[j : j + n]
            low = [t.lower() for t in g]
            if low[0] in STOP or low[-1] in STOP or sum(t in STOP for t in low) > 1:
                continue
            if low[0] in JF or low[-1] in JL or any(t in JA for t in low) or "and" in low[1:-1]:
                continue
            k = norm(" ".join(low))
            if k in GENERIC or len(k) < 8:
                continue
            out.setdefault(k, " ".join(g))
    return out


def _w(s):
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]{3,}", s.lower())}


def matches(c, ts):
    cw = _w(c)
    return any(_w(t) and len(cw & _w(t)) / len(_w(t) | cw) >= 0.5 for t in ts)


def ctfidf_extract(docs, labels, limit=40, per_cluster=2):
    """Class-based TF-IDF: phrase frequency inside a cluster x log(1 + avg docs per cluster / phrase freq overall)."""
    cl_docs = defaultdict(list)
    for i, l in enumerate(labels):
        if l >= 0:
            cl_docs[l].append(i)
    doc_grams = [grams(d["title"] + ". " + (d["snippet"].split(". ")[0] if d["snippet"] else "")) for d in docs]
    tot = Counter(k for g in doc_grams for k in g)
    avg = len(docs) / max(len(cl_docs), 1)
    surface = {}
    for g in doc_grams:
        for k, s in g.items():
            surface.setdefault(k, s)
    scored = []
    for l, idx in cl_docs.items():
        tf = Counter(k for i in idx for k in doc_grams[i])
        best = sorted(((c * math.log(1 + avg / tot[k]) * (1 + 0.3 * (len(k.split()) - 2)), k) for k, c in tf.items() if c >= 2), reverse=True)
        for rank, (s, k) in enumerate(best[:per_cluster]):
            scored.append((rank, -s * math.log(1 + len(idx)), k))
    scored.sort()
    out, taken = [], []
    for _, _, k in scored:
        if any(k in t or t in k for t in taken):
            continue
        taken.append(k)
        out.append(surface[k])
        if len(out) >= limit:
            break
    return out


e = Embedder(max_len=96)
tot_pos = tot_mp = tot_cl = tot_neg_mp = tot_neg_cl = tot_neg = 0
for dom, X in D["domains"].items():
    docs = X["docs"]
    V = e.encode([d["title"] + ". " + d["snippet"][:300] for d in docs])
    lab_true = [d["item"] for d in docs]
    agg = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average", distance_threshold=0.45).fit(V).labels_
    hdb = HDBSCAN(min_cluster_size=3, min_samples=2).fit(V).labels_
    res = {}
    for name, labels in (("agglo", agg), ("hdbscan", hdb)):
        res[name] = ctfidf_extract(docs, labels)
    pos = [(k, ts) for k, ts, p in X["members"] if p == 1]
    neg = [(k, ts) for k, ts, p in X["members"] if p == 0]

    def rec(ph, group):
        return sum(1 for _, ts in group if any(matches(c, ts) for c in ph))

    mp = X["mine_phrases"]
    print(f"== {dom}: docs={len(docs)} clusters agglo={len(set(agg))} hdbscan={len(set(hdb)) - (1 if -1 in hdb else 0)} (noise {np.mean(hdb == -1):.0%}) "
          f"ARI agglo={adjusted_rand_score(lab_true, agg):.2f} hdbscan={adjusted_rand_score(lab_true, hdb):.2f}")
    print(f"   positives matched: mine_phrases={rec(mp, pos)}/{len(pos)}  cluster-cTFIDF(agglo)={rec(res['agglo'], pos)}/{len(pos)}  (hdbscan)={rec(res['hdbscan'], pos)}/{len(pos)}")
    print(f"   negatives matched: mine_phrases={rec(mp, neg)}/{len(neg)}  cluster-cTFIDF(agglo)={rec(res['agglo'], neg)}/{len(neg)}  (hdbscan)={rec(res['hdbscan'], neg)}/{len(neg)}")
    print("   sample mine_phrases:", mp[:8])
    print("   sample cluster phrases:", res["agglo"][:8])
    tot_pos += len(pos); tot_mp += rec(mp, pos); tot_cl += rec(res["agglo"], pos)
    tot_neg += len(neg); tot_neg_mp += rec(mp, neg); tot_neg_cl += rec(res["agglo"], neg)
print(f"TOTAL positives matched: mine_phrases {tot_mp}/{tot_pos}, cluster-cTFIDF {tot_cl}/{tot_pos}; negatives matched: {tot_neg_mp}/{tot_neg} vs {tot_neg_cl}/{tot_neg}")
