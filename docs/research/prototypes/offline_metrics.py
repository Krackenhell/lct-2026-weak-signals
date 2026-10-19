"""Offline metrics over saved live_eval*.json (no network): junk, calibration, diversity, translation flags, stability."""
import json, re, sys, itertools, statistics
sys.path.insert(0, "/home/user/lct-2026-weak-signals/backend")
from app.pipeline.decide import near_duplicate, PAPER_TITLE, _key_words, _GENERIC_WORDS

CALQUE = re.compile(r"кра(ях|евых|ю)\b|побег|закалива|пакеджд|питаем|осведомл|обучающий алгоритм|ко-|самостоятельно обучающ|удалённая вычислительная", re.I)
LAT_WORD = re.compile(r"\b[a-z]{4,}\b")  # lowercase english word inside russian name ("prompts")
BROAD = re.compile(r"^(intelligent|adaptive|smart|ai-driven|neural network|deep learning|self-supervised deep learning|edge computing paradigm|intelligent edge)\b", re.I)

def fuzzy_overlap(x, y):
    used, m = set(), 0
    for a in x:
        for j, b in enumerate(y):
            if j not in used and (near_duplicate(a, b) or a.lower() in b.lower() or b.lower() in a.lower()):
                used.add(j); m += 1; break
    return m / max(len(x) + len(y) - m, 1)

def theme_max(names):
    cnt = {}
    for n in names:
        for w in _key_words(n) - _GENERIC_WORDS:
            if len(w) > 3: cnt[w] = cnt.get(w, 0) + 1
    return max(cnt.values()) if cnt else 0

def per_file(fn, mode="только обнаружение"):
    d = json.load(open(fn)); rows = []
    for r in d["runs"]:
        if r.get("status") != "done": continue
        if r.get("domain") and r.get("mode") != mode: continue
        top = r["top"]; names = [t["name"] for t in top]
        rows.append({
            "q": r.get("domain") or r["query"], "n": len(top), "sec": r.get("seconds"),
            "p_shown_100": sum(t["p"] >= 0.995 for t in top), "p_ge_95": sum(t["p"] >= 0.95 for t in top),
            "paper_title": sum(bool(PAPER_TITLE.search(nm)) or len(nm.split()) > 5 for nm in names),
            "broad": sum(bool(BROAD.search(nm)) for nm in names),
            "theme_max": theme_max(names),
            "ru_flags": [t.get("name_ru") for t in top if t.get("name_ru") and (CALQUE.search(t["name_ru"]) or LAT_WORD.search(t["name_ru"]) and re.search("[а-я]", t["name_ru"]))],
            "names": names,
        })
    return rows

if __name__ == "__main__":
    base = "/home/user/lct-2026-weak-signals/backend/data/model/"
    files = {"sep": "live_eval_before.json", "17.10": "live_eval_science_only.json", "18.10": "live_eval.json"}
    data = {k: per_file(base + v) for k, v in files.items()}
    for k, rows in data.items():
        n = sum(r["n"] for r in rows)
        print(f"== {k}: queries={len(rows)} items={n} mean_n={n/len(rows):.1f} shown_as_100%={sum(r['p_shown_100'] for r in rows)} "
              f"p>=.95={sum(r['p_ge_95'] for r in rows)} paperlike={sum(r['paper_title'] for r in rows)} broad={sum(r['broad'] for r in rows)} "
              f"theme_max={[r['theme_max'] for r in rows]} ru_flags={sum(len(r['ru_flags']) for r in rows)} sec_median={statistics.median([r['sec'] for r in rows])}")
        for r in rows:
            for f in r["ru_flags"]: print("   ru-flag:", r["q"], "|", f)
    for a, b in [("sep", "17.10"), ("17.10", "18.10"), ("sep", "18.10")]:
        A = {r["q"]: r["names"] for r in data[a]}; B = {r["q"]: r["names"] for r in data[b]}
        j = [round(fuzzy_overlap(A[q], B[q]), 2) for q in A if q in B]
        print("stability", a, "vs", b, j, "median", statistics.median(j) if j else None)
