"""Narrowed name validator: rules that do not punish the organizer's own style (long RU headline with embedded Latin terms)."""
import json, re, glob, collections

# cross-domain calque stems (not tied to one dataset): morphology/idiom errors GigaChat repeats
CALQUE = (r"базированн|на краях|краев\w* (устройств|вычисл)|через воздух|над воздухом|побег\w* из тюрьм|закалива|"
          r"осведомл[её]нн|-питаем|питаем\w* (ии|ai)|насыщенн\w* (ядр|платф)|умн\w* контракт|стабильн\w* монет|"
          r"движущ\w* цель|самоисцел|кабельно-провод|аннеллинг|стрейн|фузия|обучающ\w* (ии|алгоритм)|"
          r"реальн\w* временн|всегда-активн|редко связанн|неуникальн")
LAT_INFLECT = re.compile(r"(?<![A-Za-z\-])([a-z]{3,}(?:s|ing|ed))(?![A-Za-z\-])")  # lowercase English word with inflection

def flags(en, ru, query=""):
    out = []
    if not ru:
        return ["empty"]
    core = re.sub(r"\([^)]*\)", "", ru).strip()          # parenthetical EN gloss is allowed
    has_cyr = bool(re.search(r"[а-яё]", core, re.I))
    if has_cyr:
        for w in LAT_INFLECT.findall(core):
            out.append("latin_inflected:" + w)
    for tok in re.split(r"[\s\-/]+", core):               # mixed alphabets inside one hyphen-free token
        if re.search(r"[a-z]", tok, re.I) and re.search(r"[а-яё]", tok, re.I):
            out.append("mixed:" + tok)
    if re.search(CALQUE, core, re.I):
        out.append("calque")
    q = query.lower().strip()
    if q and len(q) >= 8 and q in ru.lower() and q not in en.lower():
        out.append("query_leak")
    en_n = len(re.findall(r"\w+", en))
    if len(core.split()) > max(7, 3 * en_n):
        out.append("too_long")
    return out

if __name__ == "__main__":
    base = "/home/user/lct-2026-weak-signals/backend/data/"
    seed = json.load(open(base + "seed/weak_signals_2026.json"))
    terms = json.load(open(base + "seed/positive_terms.json"))
    fl = [(it["name"], flags(terms[str(it["id"])][0], it["name"])) for it in seed]
    bad = [x for x in fl if x[1]]
    print("organizer gold flagged:", len(bad), "/100")
    for x in bad: print("   ", x)
    for f in ["model/live_eval.json", "model/live_eval_science_only.json"]:
        d = json.load(open(base + f)); n = k = 0
        for r in d["runs"]:
            for t in r.get("top") or []:
                if t.get("origin") == "watchlist": continue
                n += 1; ff = flags(t["name"], t.get("name_ru") or "", r["query"])
                if ff: k += 1
                print(f[-12:], r["domain"], "|", t["name"], "->", t.get("name_ru"), "::", ff)
        print(f, "flagged", k, "/", n)
