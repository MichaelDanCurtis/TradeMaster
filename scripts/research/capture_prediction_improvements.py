"""Resumable, read-only SEC and Alpaca captures for frozen follow-up research."""
import argparse,json,hashlib,time,threading
from pathlib import Path
from datetime import datetime,timezone
from concurrent.futures import ThreadPoolExecutor
import httpx

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
class Capture:
 def __init__(self,root,headers,spacing=.5):
  self.root=root;self.headers=headers;self.lock=threading.Lock();self.last=0.;self.spacing=spacing;self.client=httpx.Client(timeout=35,follow_redirects=False);self.file=root/'receipt.json';self.receipt=json.loads(self.file.read_text()) if self.file.exists() else {'responses':{},'failures':{}};self.completed=0
 def get(self,url,params,name):
  path=self.root/name
  with self.lock:
   saved=self.receipt['responses'].get(name)
  if saved:
   assert saved['url']==url and saved['params']==params and sha(path)==saved['sha256'];return json.loads(path.read_bytes())
  for attempt in range(3):
   with self.lock:
    time.sleep(max(0,self.spacing-(time.monotonic()-self.last)));self.last=time.monotonic()
   try:
    r=self.client.get(url,params=params,headers=self.headers)
    if r.status_code not in [429,500,502,503,504]:break
   except httpx.TransportError:
    if attempt==2:raise
   time.sleep(2+2*attempt)
  if r.status_code!=200:
   with self.lock:
    self.receipt['failures'][name]={'url':url,'params':params,'status':r.status_code};self.save()
   return None
  payload=r.json();path.write_bytes(r.content)
  with self.lock:
   self.receipt['responses'][name]={'url':url,'params':params,'sha256':sha(path),'bytes':len(r.content),'retrieved_at':datetime.now(timezone.utc).isoformat()};self.receipt['failures'].pop(name,None);self.completed+=1;self.save()
   if self.completed%20==0:print(self.root.name,self.completed,'new responses',flush=True)
  return payload
 def save(self):
  temp=self.file.with_suffix('.tmp');write(temp,self.receipt);temp.replace(self.file)

def provider():
 from dotenv import load_dotenv
 from tradingagents.ui.db import create_session_factory
 from tradingagents.ui.repository import UiRepository
 from tradingagents.ui.api import _resolve_market_data_provider
 load_dotenv('.env');engine,sessions=create_session_factory('sqlite:///.tradingagents-ui.db');data,_=_resolve_market_data_provider('alpaca-market-data',{},UiRepository(sessions),None);return data._headers(),engine

def main():
 ap=argparse.ArgumentParser();ap.add_argument('mode',choices=['sec','valuation','historical']);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();protocol=json.loads((a.root/'protocol.json').read_text());source=Path(protocol['source']);u=json.loads((source/'universe.json').read_text());history=json.loads((source/'universe-source/universe.json').read_text())
 if a.mode=='sec':
  c=Capture(a.root/'sec',{'User-Agent':'TradeMasterResearch/1.0 personal research desktop','Accept':'application/json'})
  ciks=sorted({str(x).zfill(10) for x in u['issuers'].values()})
  def fetch(cik):
   p=c.get(f'https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json',{},f'{cik}.json')
   if p is not None:assert int(p['cik'])==int(cik)
  with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(fetch,ciks))
  print(json.dumps({'mode':a.mode,'issuers':len(ciks),'captured':len(c.receipt['responses']),'failures':len(c.receipt['failures'])}));return
 headers,engine=provider();target=a.root/('prices' if a.mode=='valuation' else 'historical');c=Capture(target,headers,.5)
 if a.mode=='valuation':
  work=[(kind,names,j) for kind in ['raw','split'] for j in range(0,len(u['sp500_symbols']),60) for names in [u['sp500_symbols'][j:j+60]]]
  def fetch(item):
   kind,names,j=item;params={'symbols':','.join(names),'start':'2016-01-01','end':'2026-09-04T23:59:59Z','timeframe':'1Day','limit':10000,'sort':'asc','adjustment':kind,'asof':'2026-09-04','feed':'sip','currency':'USD'}
   for page in range(20):
    p=c.get('https://data.alpaca.markets/v2/stocks/bars',dict(params),f'{kind}-{j:03}-{page:02}.json')
    if p is None or not p.get('next_page_token'):return
    params['page_token']=p['next_page_token']
   raise ValueError('Pagination bound')
  with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(fetch,work))
 else:
  snaps=history['historical_snapshots'];work=[]
  for symbol in history['historical_only_symbols']:
   active=[s['date'] for s in snaps if symbol in s['symbols']];work.append((symbol,active[-1]))
  write(target/'requests.json',{'source_sha256':sha(source/'universe-source/universe.json'),'symbols_asof':work,'scope':'Former ticker identities requested as of a reported membership date; no automatic alias stitching or verified delisting payouts'})
  def fetch(item):
   symbol,asof=item;params={'symbols':symbol,'start':'2016-01-01','end':'2026-09-04T23:59:59Z','timeframe':'1Day','limit':10000,'sort':'asc','adjustment':'all','asof':asof,'feed':'sip','currency':'USD'}
   for page in range(5):
    p=c.get('https://data.alpaca.markets/v2/stocks/bars',dict(params),f'{symbol}-{page:02}.json')
    if p is None or not p.get('next_page_token'):return
    params['page_token']=p['next_page_token']
  with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(fetch,work))
 engine.dispose();print(json.dumps({'mode':a.mode,'captured':len(c.receipt['responses']),'failures':len(c.receipt['failures'])}))
if __name__=='__main__':main()
