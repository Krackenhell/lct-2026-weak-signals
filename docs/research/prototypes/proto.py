import re, sys
sys.path.insert(0, "/home/user/lct-2026-weak-signals/backend")
from app.llm.tasks import DOMAIN_LEXICON
LEX = dict(DOMAIN_LEXICON)
# fixed regexes (prototype)
fix = {}
for k, v in LEX.items():
    k2 = k.replace("|чип|", "|ии-чип|чипы? для ии|ai chip|").replace("|авто|", "|автомоб|автотранспорт|беспилотн|")
    k2 = k2.replace("энерг|energy|батар|аккумул", "энерг|energy|батар|аккумул|накопит")
    fix[k2] = v
FILLER = r"^(перспективн\w*|решени\w*|слаб\w*|сигнал\w*|технолог\w*|нов\w*|направлени\w*|тренд\w*|развити\w*|рынок|рынка|вычислени\w*|области|сфере|в|и|для|на|по|о|об|с|of|and|the|in|for)$"
def broad(q):
    words = re.findall(r"[a-zа-яё0-9\-]+", q.lower())
    content = [w for w in words if not re.match(FILLER, w)]
    if not content: return False, []
    unc = [w for w in content if not any(re.search(p, w) for p in fix)]
    # multiword lexicon patterns (интернет вещей, artificial intelligence)
    return (not unc), unc
qs = ["перспективные решения в финтехе","слабые сигналы в кибербезопасности ИИ","робототехника","edge AI и вычисления на устройствах","инфраструктура для ИИ","индустриальный ИИ","энергетика и накопители энергии","медицинские технологии","логистика и складская автоматизация","новые материалы и химия","edge AI","энергетика и накопители",
      "микрофлюидные чипы","органы на чипе","технологии многослойного графена","микрофлюидные технологии","квантовые сенсоры для медицины","твердотельные аккумуляторы","перовскитные солнечные элементы","нейроморфные чипы","агробиотех","биопечать","квантовые вычисления","спутниковая связь","беспилотные грузовики","агентные платежи","цифровые валюты центральных банков","нейроинтерфейсы","post-quantum cryptography","TinyML","кибербезопасность","ИИ-агенты"]
for q in qs:
    b, unc = broad(q)
    rows = [p[:18] for p in fix if re.search(p, q.lower())]
    print(f"{'BROAD ' if b else 'narrow'} | {q} | uncovered={unc} | rows={rows}")
