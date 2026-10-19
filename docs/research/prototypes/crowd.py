import sys
sys.path.insert(0,'/home/user/lct-2026-weak-signals/backend')
from types import SimpleNamespace as NS
from app.pipeline.decide import decide, PAPER_TITLE, near_duplicate, ORG
def A(name,p,rel=0.95):
    ans={k:{'value':v} for k,v in dict(relevance=rel,relevance_query=rel,evidence_match=0.9,is_technology=0.9,product_name=0.1,specific_tech=0.8,standard=0.1,mass_adoption=0.1,market_leaders=0.1,hype=0.1).items()}
    docs=[NS(url=f'https://arxiv.org/abs/{i}',source_type='preprint',source_name='arXiv',collector='arxiv',extra={},title='t') for i in range(5)]
    return {'c':{'name_en':name},'res':NS(ok=True,answers=ans),'features':{'log_total_works':5,'log_wiki_views':0,'age_years':3,'share_science':1},'ev':NS(docs=docs),'prob':p,'passport':{'level':'A','confirmed':5,'checked':8,'domains':3},'missing':[]}
names=['twisted bilayer graphene','rhombohedral multilayer graphene','laser-induced graphene','graphene heat spreaders','graphene oxide membranes','CVD graphene transfer','graphene-based supercapacitors','turbostratic graphene','graphene nanoribbon transistors','holey graphene electrodes','hexagonal boron nitride encapsulation','van der Waals heterostructures']
ass=[A(n,0.99-0.01*i) for i,n in enumerate(names)]
out=decide(ass,None,15)
for a,d in zip(ass,out): print('%-40s %-9s %s'%(a['c']['name_en'],d['status'],d.get('code') or d.get('rank')))
print()
for n in ['organ-on-a-chip models','lab-on-a-chip diagnostics','droplet microfluidics','paper-based microfluidic devices','digital microfluidics','microfluidic organ-on-chip','acoustofluidics','inertial microfluidics','a graphene membrane','graphene in the battery anode']:
    print('%-35s paper_title=%s org=%s'%(n,bool(PAPER_TITLE.search(n)),bool(ORG.search(n))))
mf=['droplet microfluidics','digital microfluidics','paper-based microfluidics','inertial microfluidics','microfluidic organ-on-chip','centrifugal microfluidics','acoustofluidics','open microfluidics']
out=decide([A(n,0.99-0.01*i) for i,n in enumerate(mf)],None,15)
print([ (n,d['status'],d.get('code')) for n,d in zip(mf,out)])
