"""Read-only, resumable price capture for a predeclared wide stock universe."""
from __future__ import annotations
import argparse, hashlib,json,math,threading,time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

FIELDS={'open':'o','high':'h','low':'l','close':'c','volume':'v','vwap':'vw'}
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def write(path,value):path.write_text(json.dumps(value,indent=2,allow_nan=False)+'\n')

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
    universe=json.loads((root/'universe.json').read_text());allnames=universe['sp500_symbols']+['SPY']
    target=root/'capture';target.mkdir(exist_ok=True);(target/'raw').mkdir(exist_ok=True)
    from dotenv import load_dotenv
    from tradingagents.ui.db import create_session_factory
    from tradingagents.ui.repository import UiRepository
    from tradingagents.ui.api import _resolve_market_data_provider
    from tradingagents.research.deployment_cycle_child import resolve_configured_broker
    load_dotenv('.env');engine,sessions=create_session_factory('sqlite:///.tradingagents-ui.db')
    data,_=_resolve_market_data_provider('alpaca-market-data',{},UiRepository(sessions),None);broker=resolve_configured_broker(sessions)
    headers=data._headers();brokerheaders=broker._headers();lock=threading.Lock()
    receiptpath=target/'receipt.json'
    receipt=json.loads(receiptpath.read_text()) if receiptpath.exists() else {'universe_sha256':sha(root/'universe.json'),'intent_sha256':sha(root/'intent.json'),'responses':{},'complete':False}
    if receipt['universe_sha256']!=sha(root/'universe.json') or receipt['intent_sha256']!=sha(root/'intent.json'):raise ValueError('Frozen input changed')
    def save():
        tmp=receiptpath.with_suffix('.tmp');write(tmp,receipt);tmp.replace(receiptpath)
    with lock:save()
    def get(url,params,name,auth):
        path=target/'raw'/name
        with lock: prior=receipt['responses'].get(name)
        if prior:
            if sha(path)!=prior['sha256'] or prior['params']!=params:raise ValueError('Raw checkpoint mismatch')
            return json.loads(path.read_bytes())
        if path.exists():raise ValueError('Unreceipted raw file; inspect before resume')
        for attempt in range(3):
            response=data._http_client.get(url,headers=auth,params=params,timeout=30,allow_redirects=False)
            if response.status_code==200:break
            if response.status_code not in (429,500,502,503,504):raise RuntimeError(f'Capture HTTP {response.status_code}')
            time.sleep(min(30,max(1,int(response.headers.get('Retry-After','3')))))
        else:raise RuntimeError('Capture exhausted bounded read retries')
        path.write_bytes(response.content)
        with lock:
            receipt['responses'][name]={'sha256':sha(path),'bytes':len(response.content),'url':url,'params':dict(params),'observed_at':datetime.now(timezone.utc).isoformat()};save()
        return response.json()
    calendar=get('https://paper-api.alpaca.markets/v2/calendar',{'start':'2016-01-01','end':'2026-09-04'},'calendar.json',brokerheaders)
    dates=sorted(r['date'] for r in calendar);assert dates[-1]=='2026-09-04' and len(set(dates))==len(dates)
    chunks=[allnames[i:i+80] for i in range(0,len(allnames),80)]
    def capture_chunk(item):
        chunk,names=item;pages=[];seen=set();count=0
        params={'symbols':','.join(names),'start':'2016-01-01','end':'2026-09-04T23:59:59Z','timeframe':'1Day','limit':10000,'sort':'asc','adjustment':'all','asof':'2026-09-04','feed':'sip','currency':'USD'}
        for page in range(30):
            payload=get('https://data.alpaca.markets/v2/stocks/bars',params,f'bars-{chunk:02}-{page:02}.json',headers)
            pages.append(payload);count+=sum(len(v) for v in payload['bars'].values())
            print(f'Chunk {chunk+1}/{len(chunks)} page {page+1}: {count} bars',flush=True)
            token=payload.get('next_page_token')
            if not token:return pages
            if token in seen:raise ValueError('Pagination token repeated')
            seen.add(token);params['page_token']=token
        raise ValueError('Page bound exceeded')
    with ThreadPoolExecutor(max_workers=3) as pool:
        chunkpages=list(pool.map(capture_chunk,enumerate(chunks)))
    records={s:{} for s in allnames};anomalies=[]
    for pages in chunkpages:
        for payload in pages:
            for symbol,bars in payload['bars'].items():
                if symbol not in records:raise ValueError('Unrequested symbol')
                for b in bars:
                    day=datetime.fromisoformat(b['t'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                    if day in records[symbol]:raise ValueError(f'Duplicate {symbol} {day}')
                    values={f:float(b[k]) for f,k in FIELDS.items()}
                    if not all(math.isfinite(v) and (v>=0 if k in ('volume','vwap') else v>0) for k,v in values.items()):raise ValueError(f'Invalid prices {symbol} {day}')
                    if values['low']>min(values['open'],values['close'])+1e-5 or values['high']<max(values['open'],values['close'])-1e-5:anomalies.append({'symbol':symbol,'date':day,'kind':'inconsistent_ohlc'})
                    if values['vwap']==0: values['vwap']=None
                    if values['volume']==0:
                        values['open']=None
                        anomalies.append({'symbol':symbol,'date':day,'kind':'zero_volume_open_not_executable'})
                    records[symbol][day]=values
    source_receipt=target/'source-receipt.json'
    write(source_receipt,{k:receipt[k] for k in ('universe_sha256','intent_sha256','responses')})
    panel={'dates':dates,'symbols':universe['sp500_symbols'],'benchmark':'SPY','series':{s:{f:[records[s].get(d,{}).get(f) for d in dates] for f in FIELDS} for s in allnames},
        'sectors':universe['sectors'],'issuers':universe['issuers'],'universe_scope':'Current S&P500 roster asof2026Sep4; survivor-selected historical diagnostic; not historicalmembership',
        'membership':None,'capture_source_sha256':sha(source_receipt)}
    missing={}
    for s in allnames:
        available=sorted(set(records[s])&set(dates));between=[d for d in dates if available and available[0]<=d<=available[-1] and d not in records[s]]
        missing[s]={'bars':len(available),'first':available[0] if available else None,'last':available[-1] if available else None,'interior_missing':between,'total_missing':len(dates)-len(available),'zero_volume':[d for d in available if records[s][d]['volume']==0]}
    write(root/'panel-sp500.json',panel)
    selected=universe['diverse100_symbols'];small={**panel,'symbols':selected,'series':{s:panel['series'][s] for s in selected+['SPY']},'sectors':{s:panel['sectors'][s] for s in selected},'issuers':{s:panel['issuers'][s] for s in selected},'universe_scope':'Sector-balanced seeded100 subset of current S&P500; survivor-selected diagnostic'}
    write(root/'panel-diverse100.json',small)
    write(target/'coverage.json',{'sessions':len(dates),'symbols':len(allnames),'bars':sum(len(r) for r in records.values()),'per_symbol':missing,'anomalies':anomalies,'policy':'Missing values preserved as null; never forward filled, never future-completeness filtered'})
    with lock:
        receipt['complete']=True;receipt['source_receipt_sha256']=sha(source_receipt);receipt['panel_sha256']={name:sha(root/name) for name in ['panel-sp500.json','panel-diverse100.json']};save()
    engine.dispose();print(json.dumps({'state':'captured','bars':sum(len(r) for r in records.values()),'symbols':len(allnames),'interior_gap_symbols':[s for s,v in missing.items() if v['interior_missing']],'ohlc_anomalies':len(anomalies)}))
if __name__=='__main__':main()
