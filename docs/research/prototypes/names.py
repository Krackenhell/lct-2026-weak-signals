import json, re, glob
pairs = []
base = '/home/user/lct-2026-weak-signals/backend/data/'
for f in ['model/live_eval.json', 'model/live_eval_before.json', 'model/live_eval_science_only.json', 'model/live_eval_v1.json']:
    d = json.load(open(base + f))
    for r in d['runs']:
        for t in r.get('top', []):
            if t.get('origin') == 'watchlist':
                continue
            pairs.append((f.split('/')[-1], r['query'], t['name'], t.get('name_ru') or ''))
for f in ['run1', 'run2', 'run3', 'run4', 'r1']:
    d = json.load(open(base + f + '.json'))
    for c in d.get('signals', []) + d.get('excluded', []):
        pairs.append((f, d['query'], c['name'], c.get('name_ru') or ''))
seen = set(); uniq = []
for p in pairs:
    if (p[2].lower(), p[3]) in seen: continue
    seen.add((p[2].lower(), p[3])); uniq.append(p)

CALQUES = r"закалив|на краях|краев\w* устройств|через воздух|побег\w* из тюрьм|питаем|насыщенн|осведомл|базированн|цельносвяз|кросс-бордюр|подкрепляющ\w* обучен|стабильн\w* монет|модельного контекста|вывод TEE|высокозернист|интеллектуальный край|движущаяся цель|самоисцелен|здоровья актуатор|кабельно-провод|экологическ\w* перцепц|стрейн|аннеллинг|фузия|обучающ\w* ИИ|обучающий алгоритм|удалённая вычислительн|умных контракт"
def flags(en, ru, query):
    out = []
    if not ru:
        out.append('нет перевода')
        return out
    if ru.strip().lower() == en.strip().lower():
        out.append('не переведено (англ. как есть)')
    # Latin word inflected/placed inside Russian phrase (not acronym, not in parentheses)
    outside_paren = re.sub(r"\([^)]*\)", "", ru)
    if re.search(r"[а-яё]", outside_paren, re.I):
        lat = re.findall(r"\b[a-z][a-z\-]{3,}\b", outside_paren)
        if lat:
            out.append('латиница внутри русской фразы: ' + ','.join(lat))
    if re.search(CALQUES, ru, re.I):
        out.append('калька/ошибка из стоп-листа')
    qwords = [w for w in re.findall(r"[а-яё]{5,}", query.lower())]
    if query and query.lower()[:20] in ru.lower():
        out.append('в название попал текст запроса')
    if len(ru.split()) > max(4, 2.2 * len(en.split())):
        out.append('слишком длинно (пересказ вместо термина)')
    if re.search(r"[a-z][а-яё]|[а-яё][a-z]", ru, re.I):
        out.append('смесь алфавитов в слове')
    return out

flagged = [(p, flags(p[2], p[3], p[1])) for p in uniq]
bad = [(p, f) for p, f in flagged if f and 'нет перевода' not in f]
print('total pairs', len(uniq), 'with name_ru', sum(1 for p in uniq if p[3]), 'flagged', len(bad))
for p, f in bad:
    print(f'{p[2]} -> {p[3]}  ::  {"; ".join(f)}')

# Честная оценка: только общие правила (без стоп-листа, подогнанного под эти данные), только найденные (не из датасета) названия
import collections
ds = json.load(open(base + 'seed/weak_signals_2026.json'))
ds_names = {x['name'] for x in ds}
gen = collections.Counter(); n = 0; nflag = 0
for p in uniq:
    if not p[3] or p[3] in ds_names: continue
    n += 1
    f = [x for x in flags(p[2], p[3], p[1]) if 'стоп-лист' not in x]
    if f: nflag += 1
    for x in f: gen[x.split(':')[0]] += 1
print('discovered names with name_ru', n, 'flagged by generic rules', nflag, gen)
