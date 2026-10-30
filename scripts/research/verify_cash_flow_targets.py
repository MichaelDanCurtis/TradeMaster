"""Independent scalar arithmetic and timing audit before portfolio outcomes."""
import argparse,math
from pathlib import Path
import numpy as np
from scripts.research.event_research_pilot import read,write_new,digest,now
from scripts.research.cash_flow_pilot import check


def run(root):
    p=check(root);lock=read(root/'targets-lock.json');events=[]
    for filename,h in lock.items():
        assert digest(root/filename)==h;e=read(root/filename)
        g=np.load(root/f"{e['id']}-graph.npz",allow_pickle=False);cash=g['cash'];weights=g['weights'];owners=list(g['managers'])
        assert weights.shape==(len(cash),len(e['mapping']))
        assert len(owners)==len(set(owners)) and np.isfinite(weights).all() and (weights>=0).all()
        assert np.all(weights.sum(axis=1)<=1+1e-10)
        assert e['entry']>e['completed'] and e['exit_index']-e['entry_index']==10
        assert all(x['filed']<=e['completed'] and x['reported']<=x['filed'] for x in e['report_selection'].values())
        assert len({x['symbol'] for x in e['mapping']})==len({x['cusip'] for x in e['mapping']})==len(e['mapping'])
        for j,m in enumerate(e['mapping']):
            calculated=math.fsum(float(c)*float(w) for c,w in zip(cash,weights[:,j]))
            assert math.isclose(calculated,m['demand_usd'],rel_tol=1e-10,abs_tol=1e-7)
            assert math.isclose(calculated/m['adv20'],m['demand_adv'],rel_tol=1e-10,abs_tol=1e-12)
        chosen=sorted([x for x in e['mapping'] if x['demand_usd']>0],key=lambda x:(-x['demand_adv'],x['symbol']))[:10]
        assert set(e['portfolios']['cash_flow'])=={m['symbol'] for m in chosen}
        assert all(math.isclose(sum(w.values()),.2,abs_tol=1e-10) for w in e['portfolios'].values())
        events.append({'id':e['id'],'cash_holders':e['cash_holders'],'mapped_stocks':e['destinations'],'selected':sorted(e['portfolios']['cash_flow']),'checks':'passed'})
    write_new(root/'pre-score-verification.json',{'verified_at':now(),'scope':'Independent scalar graph multiplication, timing, concentration and ranking; same source extraction. No return labels used.','events':events})
    write_new(root/'pre-score-lock.json',{str(f.relative_to(root)):digest(f) for f in root.iterdir() if f.is_file() and f.name!='pre-score-lock.json'})
    print(events)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);run(ap.parse_args().root)
