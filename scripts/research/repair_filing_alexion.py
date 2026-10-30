"""Versioned ALXN entitlement repair; no selection or frozen artifact mutation."""
import argparse, copy, json, math
from pathlib import Path
import httpx
from scripts.research.event_research_pilot import read, write_new, digest, now
from scripts.research.capture_prediction_improvements import Capture, provider
from scripts.research.prediction_event_accounting import simulate_events
from scripts.research.evaluate_astra_capsules import compare_recursive

SOURCES = {
 'alexion-occ.pdf':'https://infomemo.theocc.com/infomemos?number=49014',
 'alexion-completed.html':'https://www.astrazeneca.com/media-centre/press-releases/2021/acquisition-of-alexion-completed.html',
 'biogen-halt.pdf':'https://infomemo.theocc.com/infomemos?number=47809',
}

def run(root, parent):
    root.mkdir(parents=True, exist_ok=False)
    cfg=read(parent/'protocol.json'); panel_path=Path(cfg['panel'])
    code=[Path(__file__).resolve(),Path('scripts/research/prediction_event_accounting.py').resolve(),Path('scripts/research/capture_prediction_improvements.py').resolve()]
    protocol={'created_at':now(),'parent':str(parent.resolve()),'inputs':{str(p.resolve()):digest(p) for p in [parent/'targets.json',parent/'targets-lock.json',parent/'results.json',panel_path,Path('.research-artifacts/filing-event-web-review-2026-09-08/web-extracts.json')]},
      'code':{str(p):digest(p) for p in code},'scope':'Valuation amendment after initial incomplete replay. Same selections, dates and costs. No new alpha hypothesis.',
      'event':{'old':'ALXN','date':'2021-07-21','cash_per_raw_share':60.,'successors':[{'symbol':'AZN','ratio':2.1243}]},
      'settlement':'Economic entitlement from completion before July 21 open. New ADS trading July 22; no rebalance until September 3. Fractional entitlements retained, cash credited without transaction fee; not broker settlement replication.',
      'halt':'BIIB 2020-11-06 remains missing. No fills invented; daily risk statistics unqualified.',
      'sources':SOURCES}
    assert digest(parent/'targets.json')==read(parent/'targets-lock.json')['sha256']
    write_new(root/'protocol.json',protocol)
    receipts={}
    with httpx.Client(timeout=60,follow_redirects=True) as client:
        for name,url in SOURCES.items():
            r=client.get(url,headers={'User-Agent':'TradeMasterResearch/1.0 personal research desktop'})
            receipts[name]={'url':url,'status':r.status_code,'retrieved_at':now()}
            if r.status_code==200:
                (root/name).write_bytes(r.content);receipts[name]['sha256']=digest(root/name)
            else:receipts[name]['fallback']='Separately archived public web-tool extract; no access-control bypass or original PDF claim'
    write_new(root/'sources-receipt.json',receipts)
    import subprocess
    (root/'prices').mkdir()
    # Credential resolution stays in the application environment; secrets never
    # cross the process boundary. Only sanitized capture files are shared.
    subprocess.run([str(Path('.venv/bin/python').absolute()), '-c', """
import sys
from pathlib import Path
from scripts.research.capture_prediction_improvements import Capture, provider
headers,engine=provider();capture=Capture(Path(sys.argv[1]),headers)
try:
    for symbol,adjustment in [('ALXN','raw'),('AZN','raw'),('AZN','all')]:
        params={'symbols':symbol,'start':'2021-06-01','end':'2021-09-03T23:59:59Z','timeframe':'1Day','limit':10000,'sort':'asc','adjustment':adjustment,'asof':'2021-07-20','feed':'sip','currency':'USD'}
        result=capture.get('https://data.alpaca.markets/v2/stocks/bars',params,f'{symbol}-{adjustment}.json')
        assert result and not result.get('next_page_token')
finally:
    capture.client.close();engine.dispose()
""", str(root/'prices')],check=True)
    bars={}
    receipt=read(root/'prices/receipt.json')['responses']
    for symbol,adjustment in [('ALXN','raw'),('AZN','raw'),('AZN','all')]:
        name=f'{symbol}-{adjustment}.json';path=root/'prices'/name
        assert digest(path)==receipt[name]['sha256']
        bars[symbol,adjustment]={b['t'][:10]:b for b in read(path)['bars'][symbol] if b['v']>0}
    panel=read(panel_path);dates=panel['dates'];ix={d:i for i,d in enumerate(dates)};event=copy.deepcopy(protocol['event']);day=event['date']
    raw=bars['ALXN','raw'];prior=max(d for d in raw if d<day and d in ix and panel['series']['ALXN']['close'][ix[d]] is not None)
    factor=panel['series']['ALXN']['close'][ix[prior]]/raw[prior]['c']
    assert math.isfinite(factor) and factor>0
    event.update(old_adjustment_factor=factor,factor_anchor_date=prior)
    all_bars=bars['AZN','all'];raw_bars=bars['AZN','raw'];existing=panel['series'].get('AZN',{}).get('open',[None]*len(dates))
    overlap=[d for d in all_bars if d>=day and d in ix and existing[ix[d]] is not None]
    scale=existing[ix[min(overlap)]]/all_bars[min(overlap)]['o'] if overlap else 1.
    for d in overlap:assert math.isclose(existing[ix[d]],all_bars[d]['o']*scale,rel_tol=2e-5,abs_tol=1e-5),(d,'AZN revision')
    event['successors'][0]['adjustment_factor']=all_bars[day]['o']*scale/raw_bars[day]['o']
    assert event['successors'][0]['adjustment_factor']>0
    if 'AZN' not in panel['series']:panel['series']['AZN']={k:[None]*len(dates) for k in ['open','close','volume']}
    for d,b in all_bars.items():
        if d>=day and d in ix and panel['series']['AZN']['open'][ix[d]] is None:panel['series']['AZN']['open'][ix[d]]=b['o']*scale
    if 'AZN' not in panel['symbols'] and 'AZN' not in panel.get('successor_only_symbols',[]):panel.setdefault('successor_only_symbols',[]).append('AZN')
    events=panel['valuation_only_reconciliation']['events']+[event]
    panel['valuation_only_reconciliation']['events']=events
    write_new(root/'event.json',event);write_new(root/'panel.json',panel)
    write_new(root/'accounting-lock.json',{'created_at':now(),'files':{n:digest(root/n) for n in ['protocol.json','event.json','panel.json']},'targets_sha256':digest(parent/'targets.json')})
    decisions=read(parent/'targets.json')['decisions'];pos={s:i for i,s in enumerate(panel['symbols'])};rows=[]
    for j,d in enumerate(decisions):
        w=[0.]*(len(pos)+1)
        for s in d['selected']:w[pos[s]]=1/len(d['selected'])
        rows.append({'entry_index':ix[d['date']],'exit_index':ix[decisions[j+1]['date'] if j+1<len(decisions) else cfg['liquidation']],'target_weights':w})
    assert not any(dates[r['entry_index']] in ['2021-07-21','2021-07-22'] for r in rows)
    out={'filing_stability':{},'SPY_buy_hold':{}}
    for name,targets in [('filing_stability',rows),('SPY_buy_hold',[{**rows[0],'exit_index':rows[-1]['exit_index'],'target_weights':[0.]*len(pos)+[1.]}])]:
        for bps in cfg['rules']['costs_bps_per_side']:
            a=simulate_events(panel,targets,events,bps/10000);b=simulate_events(panel,targets,events,bps/10000,True);compare_recursive(a,b)
            out[name][str(bps)]=a
            print(json.dumps({'variant':name,'bps':bps,**{k:v for k,v in a.items() if k in ['state','cagr','net_return','max_drawdown','valuation_gaps','unresolved_symbols']}}),flush=True)
    for bps,a in out['filing_stability'].items():
        if a['state']=='complete':a['excess_cagr_to_spy']=a['cagr']-out['SPY_buy_hold'][bps]['cagr']
    assert all(digest(p)==h for p,h in protocol['inputs'].items())
    write_new(root/'results.json',{'results':out,'independent_trade_replay':'passed separate rebalance arithmetic; shared event sequencing','matched_control':'Initial eligible control remains incomplete pending separate corporate-action accounting. No alpha attribution yet.','limitations':cfg['limitations']})
    write_new(root/'manifest.json',{str(p.relative_to(root)):digest(p) for p in root.rglob('*') if p.is_file()})

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--parent',type=Path,required=True);a=ap.parse_args();run(a.root,a.parent)
