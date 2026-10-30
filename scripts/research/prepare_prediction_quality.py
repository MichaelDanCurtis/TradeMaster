"""Preserve prices, quarantine independently identified training discontinuities."""
import argparse,json,hashlib
from datetime import datetime,timezone
from pathlib import Path
EVENTS=[{'symbol':'APTV','date':'2017-12-05','reason':'Powertrain spin-off and rename; adjacent legacy/new closes do not establish holder total return'},
 {'symbol':'RTX','date':'2020-04-03','reason':'UTX spin-offs and RTN merger; unqualified security lineage/distribution adjustments'},
 {'symbol':'EQT','date':'2018-11-13','reason':'ETRN distribution; adjacent closes do not establish holder total return'}]
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();root=a.root
 protocol={'declared_at':datetime.now(timezone.utc).isoformat(),'scope':'Data-quality sensitivity after initialresults; not independentholdout or modelretuning','events':EVENTS,
 'policy':['All originalrawprices, panels andresults retained','Each affected close becomesnull on eventdate, excluding lookbacks that crossit','Each affected open from21sessionsbeforethrough21sessionsafter becomesnull to conservativelyexclude maturetrainingendpointlabels thatcouldcrossdiscontinuity','No post2021 prices or membership, sectorselection, strategyparameters changed','Nulls are quarantine masks, not adjusted prices or claims of missing provider bars','This does notqualify all corporateactions or remove current-survivor bias']}
 out=root/'quality-protocol.json'
 with out.open('x') as f:json.dump(protocol,f,indent=2)
 receipts=[]
 for name in ['diverse100','sp500']:
  src=root/f'panel-{name}.json';p=json.loads(src.read_text());applied=[]
  for event in EVENTS:
   if event['symbol'] not in p['symbols']:continue
   i=p['dates'].index(event['date']);s=p['series'][event['symbol']];s['close'][i]=None
   for j in range(i-21,i+22):s['open'][j]=None
   applied.append({**event,'quarantined_open_start':p['dates'][i-21],'quarantined_open_end':p['dates'][i+21]})
  p['data_quality_quarantine']={'original_panel_sha256':sha(src),'protocol_sha256':sha(out),'events':applied}
  dest=root/f'panel-{name}-quality.json'
  with dest.open('x') as f:json.dump(p,f,indent=2,allow_nan=False);f.write('\n')
  receipts.append({'universe':name,'original_panel_sha256':sha(src),'derived_panel_sha256':sha(dest),'applied':applied})
 (root/'quality-receipt.json').write_text(json.dumps(receipts,indent=2)+'\n')
 print(json.dumps(receipts))
if __name__=='__main__':main()
