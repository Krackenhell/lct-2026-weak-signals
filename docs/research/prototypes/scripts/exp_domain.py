import os
"""Exp A: can an embedding relevance score tell in-domain from neighbouring-domain technologies?

Uses saved evidence (training_evidence.json) for the 100 organizer signals + team negatives,
each labelled with one of 6 domains. Scores each item against 6 domain queries and reports
6-way accuracy and macro one-vs-rest AUC for different query/candidate representations.
"""
import json
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts") if os.path.basename(os.path.dirname(os.path.abspath(__file__))) != "scripts" else os.path.dirname(os.path.abspath(__file__)))
from emb import Embedder  # noqa: E402

B = "/home/user/lct-2026-weak-signals/backend/"
items = json.load(open(B + "data/seed/weak_signals_2026.json"))
terms = json.load(open(B + "data/seed/positive_terms.json"))
negs = json.load(open(B + "data/seed/negatives.json"))["items"]
ev = json.load(open(B + "data/model/training_evidence.json"))
DOMS = ["Финтех", "Защита ИИ", "Роботы", "Edge", "Инфраструктура ИИ", "Индустриальный ИИ"]
Q_PLAIN = {"Финтех": "fintech", "Защита ИИ": "AI security", "Роботы": "robotics", "Edge": "edge AI and on-device computing",
           "Инфраструктура ИИ": "AI infrastructure", "Индустриальный ИИ": "industrial AI"}
# Neutral one-sentence scope descriptions, as an LLM would write them from the query (no dataset terms).
Q_DESC = {
    "Финтех": "Financial technology: new ways to pay, lend, bank, invest, insure and comply with financial regulation using software, cryptography and AI.",
    "Защита ИИ": "Security of AI systems: protecting machine learning models, LLMs and AI agents from attacks, misuse, data leaks and unsafe behaviour.",
    "Роботы": "Robotics: robots, their bodies, actuators, sensors, manipulation, locomotion, control and robot learning.",
    "Edge": "Edge AI: running AI models on devices such as phones, sensors, microcontrollers and vehicles instead of the cloud, under power and memory limits.",
    "Инфраструктура ИИ": "AI infrastructure: hardware, data centers, chips, memory, networking, power and cooling used to train and serve AI models.",
    "Индустриальный ИИ": "Industrial AI: applying AI in factories, plants, process industries, energy and supply chains for design, control, inspection and operations.",
}

rows = []  # (domain, name, evidence texts, is_pos)
for it in items:
    rows.append((it["domain"], terms[str(it["id"])][0], ev.get(f"pos-{it['id']}", []), 1))
for i, n in enumerate(negs):
    if n.get("domain") in DOMS:
        rows.append((n["domain"], n["terms"][0] if n.get("terms") else n["name"], ev.get(f"neg-{i}", []), 0))
print("items", len(rows), "with evidence", sum(1 for r in rows if r[2]))

e = Embedder(max_len=96)
name_v = e.encode([r[1] for r in rows])
ev_v = []
for r in rows:
    txt = [f"{d['title']}. {d.get('snippet', '')[:300]}" for d in r[2][:12]]
    if txt:
        v = e.encode(sorted(txt, key=len)).mean(0)
        ev_v.append(v / np.linalg.norm(v))
    else:
        ev_v.append(np.zeros(name_v.shape[1]))
ev_v = np.array(ev_v)
mix_v = name_v + ev_v
mix_v /= np.linalg.norm(mix_v, axis=1, keepdims=True)
qp = e.encode([Q_PLAIN[d] for d in DOMS])
qd = e.encode([Q_DESC[d] for d in DOMS])
qpd = qp + qd
qpd /= np.linalg.norm(qpd, axis=1, keepdims=True)
y = np.array([DOMS.index(r[0]) for r in rows])
has_ev = np.array([bool(r[2]) for r in rows])
pos = np.array([r[3] for r in rows]) == 1


def report(label, C, Q, mask):
    S = C[mask] @ Q.T
    yy = y[mask]
    acc = (S.argmax(1) == yy).mean()
    aucs = [roc_auc_score(yy == k, S[:, k]) for k in range(len(DOMS))]
    # relative score: own-domain sim minus mean sim to other domains (what a gate would use)
    print(f"{label:38s} n={mask.sum():3d} acc6={acc:.2f} macroAUC={np.mean(aucs):.3f} per-domain=" + " ".join(f"{a:.2f}" for a in aucs))


for qlab, Q in (("plain query", qp), ("query+description", qpd)):
    for clab, C in (("name", name_v), ("evidence centroid", ev_v), ("name+evidence", mix_v)):
        report(f"{qlab} | {clab}", C, Q, has_ev)
print("--- positives only (organizer signals) ---")
for clab, C in (("name", name_v), ("name+evidence", mix_v)):
    report(f"query+description | {clab}", C, qpd, has_ev & pos)
