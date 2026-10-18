import re, sys, json
sys.path.insert(0,'/home/user/lct-2026-weak-signals/backend')
from app.llm.tasks import rule_check_query, fallback_plan, DOMAIN_LEXICON
from app.pipeline import discovery
from app.collectors import news_search
from app.pipeline.passport import bank_area
QS=["технология многослойного графена","микрофлюидные чипы","микрофлюидные технологии","технологии многослойного графена","перовскитные солнечные элементы","органоиды на чипе","твердотельные аккумуляторы","CRISPR-диагностика","metamaterials for 6G"]
TOPICS={"технология многослойного графена":"multilayer graphene","микрофлюидные чипы":"microfluidic chips","микрофлюидные технологии":"microfluidics","технологии многослойного графена":"multilayer graphene technology","перовскитные солнечные элементы":"perovskite solar cells","органоиды на чипе":"organ-on-chip","твердотельные аккумуляторы":"solid-state batteries","CRISPR-диагностика":"CRISPR diagnostics","metamaterials for 6G":"metamaterials 6G"}
for q in QS:
    t=TOPICS[q]
    print('=====',q,'| topic_en guess:',t)
    print(' rule_check:',rule_check_query(q))
    fp=fallback_plan(q); print(' fallback_plan subqueries:',fp['subqueries'][:12])
    hits=[p for p in DOMAIN_LEXICON if re.search(p,q.lower())]; print(' lexicon patterns hit:',hits)
    dom={d for d,pat in discovery.WATCHLIST_DOMAINS.items() if re.search(pat,q.lower())}; print(' watchlist domains:',dom)
    txt=q+' '+t
    print(' EuropePMC (LIFE_SCIENCE):',bool(re.search(discovery.LIFE_SCIENCE,txt,flags=re.I)))
    print(' HF/OpenReview (AI|robot|edge|comput|data...):',bool(re.search(discovery.AI_QUERY + r"|robot|робот|edge|вычисл|comput|данн|data|агент|agent",txt,flags=re.I)))
    themed=[f"{f[1]}:{f[0].split('/')[-3] if 'category' in f[0] else ''}" for f in news_search.FEEDS if f[2]=='en' and f[3] and re.search(f[3],txt,flags=re.I)]
    print(' themed EN feeds (all entries taken):',themed)
