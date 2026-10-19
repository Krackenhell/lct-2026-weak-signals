import os
"""H8 check: does a TF-IDF (default) or MiniLM scope score separate in-domain vs other-domain items,
with anchors written a priori (not tuned on the items)? Proxy only: real pools come from a topic corpus."""
import json
import sys

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import roc_auc_score
from scipy.sparse import hstack

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scripts") if os.path.basename(os.path.dirname(os.path.abspath(__file__))) != "scripts" else os.path.dirname(os.path.abspath(__file__)))
from emb import Embedder  # noqa: E402

B = "/home/user/lct-2026-weak-signals/backend/"
items = json.load(open(B + "data/seed/weak_signals_2026.json"))
terms = json.load(open(B + "data/seed/positive_terms.json"))
negs = json.load(open(B + "data/seed/negatives.json"))["items"]
ev = json.load(open(B + "data/model/training_evidence.json"))
DOMS = ["Финтех", "Защита ИИ", "Роботы", "Edge", "Инфраструктура ИИ", "Индустриальный ИИ"]
SCOPE = {
    "Финтех": "Financial technology: new ways to pay, lend, bank, invest, insure and comply with financial regulation using software, cryptography and AI.",
    "Защита ИИ": "Security of AI systems: protecting machine learning models, LLMs and AI agents from attacks, misuse, data leaks and unsafe behaviour.",
    "Роботы": "Robotics: robots, their bodies, actuators, sensors, manipulation, locomotion, control and robot learning.",
    "Edge": "Edge AI: running AI models on devices such as phones, sensors, microcontrollers and vehicles instead of the cloud, under power and memory limits.",
    "Инфраструктура ИИ": "AI infrastructure: hardware, data centers, chips, memory, networking, power and cooling used to train and serve AI models.",
    "Индустриальный ИИ": "Industrial AI: applying AI in factories, plants, process industries, energy and supply chains for design, control, inspection and operations.",
}
# A-priori "adjacent areas" as an LLM would write from the query alone (generic, not tuned on items).
OOS = {
    "Финтех": ["general enterprise IT and cloud software", "macroeconomics and monetary policy", "cryptocurrency price speculation and trading news"],
    "Защита ИИ": ["general IT network security and firewalls", "AI ethics and policy debates", "using AI to improve unrelated business processes"],
    "Роботы": ["pure software AI without physical embodiment", "materials science", "industrial automation business news"],
    "Edge": ["cloud data center AI training", "telecommunications network business", "consumer electronics product reviews"],
    "Инфраструктура ИИ": ["AI applications in specific industries", "machine learning algorithms and model architectures", "quantum computing algorithms"],
    "Индустриальный ИИ": ["consumer AI apps and chatbots", "general manufacturing economics", "robotics research in laboratories"],
}

rows = []
for it in items:
    rows.append((it["domain"], terms[str(it["id"])][0], ev.get(f"pos-{it['id']}", []), 1))
for i, n in enumerate(negs):
    if n.get("domain") in DOMS:
        rows.append((n["domain"], n["terms"][0] if n.get("terms") else n["name"], ev.get(f"neg-{i}", []), 0))
rows = [r for r in rows if r[2]]
text_nt = [r[1] + ". " + ". ".join(d["title"] for d in r[2][:6]) for r in rows]
text_n = [r[1] for r in rows]
y_dom = np.array([r[0] for r in rows])
print("items", len(rows))

e = Embedder(max_len=128)


def tfidf_scores(texts, scope, oos):
    docs = texts + [scope] + oos
    w = TfidfVectorizer(analyzer="word", ngram_range=(1, 2), sublinear_tf=True, stop_words="english").fit(docs)
    c = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), sublinear_tf=True).fit(docs)
    X = hstack([w.transform(docs), c.transform(docs)]).tocsr()
    from sklearn.preprocessing import normalize
    X = normalize(X)
    T, S, O = X[: len(texts)], X[len(texts)], X[len(texts) + 1 :]
    s = (T @ S.T).toarray().ravel()
    o = (T @ O.T).toarray().max(1)
    return s, s - o


def emb_scores(V, scope, oos):
    S = e.encode([scope])[0]
    O = e.encode(oos)
    s = V @ S
    return s, s - (V @ O.T).max(1)


V_nt = e.encode(text_nt)
V_n = e.encode(text_n)
res = {k: [] for k in ["tfidf_cos", "tfidf_contr", "minilm_cos", "minilm_contr", "minilm_name_cos", "tfidf_name_cos"]}
for d in DOMS:
    y = (y_dom == d).astype(int)
    s1, s2 = tfidf_scores(text_nt, SCOPE[d], OOS[d])
    s3, s4 = emb_scores(V_nt, SCOPE[d], OOS[d])
    s5, _ = emb_scores(V_n, SCOPE[d], OOS[d])
    s6, _ = tfidf_scores(text_n, SCOPE[d], OOS[d])
    for k, s in zip(res, [s1, s2, s3, s4, s5, s6]):
        res[k].append(roc_auc_score(y, s))
    print(d, y.sum(), " ".join(f"{k}={roc_auc_score(y, s):.2f}" for k, s in zip(res, [s1, s2, s3, s4, s5, s6])))
print("MEAN", {k: round(float(np.mean(v)), 3) for k, v in res.items()})

print("\n--- within-domain: does scope similarity prefer weak signals (pos) over mature/broad negatives? AUC>0.5 = prefers signals")
is_pos = np.array([r[3] for r in rows])
for d in DOMS:
    m = y_dom == d
    s1, _ = tfidf_scores(text_nt, SCOPE[d], OOS[d])
    s3, _ = emb_scores(V_nt, SCOPE[d], OOS[d])
    s5, _ = emb_scores(V_n, SCOPE[d], OOS[d])
    print(d, "pos", is_pos[m].sum(), "neg", (~is_pos[m].astype(bool)).sum(),
          f"tfidf={roc_auc_score(is_pos[m], s1[m]):.2f} minilm_nt={roc_auc_score(is_pos[m], s3[m]):.2f} minilm_name={roc_auc_score(is_pos[m], s5[m]):.2f}")

print("\n--- prescreen simulation: pool = in-domain items + off-topic (15% of pool) ; keep top 35/80 share by score; share of in-domain positives lost")
rng = np.random.default_rng(0)
for d in DOMS:
    m_in = np.where(y_dom == d)[0]
    m_out = np.where(y_dom != d)[0]
    lost = {"tfidf": [], "minilm": [], "random": []}
    s1, _ = tfidf_scores(text_nt, SCOPE[d], OOS[d])
    s3, _ = emb_scores(V_nt, SCOPE[d], OOS[d])
    for rep in range(200):
        n_out = int(round(len(m_in) * 0.15 / 0.85))
        pool = np.concatenate([m_in, rng.choice(m_out, n_out, replace=False)])
        k = int(round(len(pool) * 35 / 80))
        for lab, s in (("tfidf", s1), ("minilm", s3), ("random", rng.random(len(rows)))):
            kept = set(pool[np.argsort(-s[pool])[:k]])
            pos_in = [i for i in m_in if is_pos[i]]
            out_kept = sum(1 for i in pool if i in kept and y_dom[i] != d)
            lost[lab].append((1 - sum(i in kept for i in pos_in) / len(pos_in), out_kept / n_out))
    print(d, " ".join(f"{lab}: pos_lost={np.mean([a for a,_ in v]):.2f} offtopic_kept={np.mean([b for _,b in v]):.2f}" for lab, v in lost.items()))
