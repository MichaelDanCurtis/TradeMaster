"""Prepare model-only past evidence; keep mappings and outcomes outside packets."""
from pathlib import Path
import argparse,json,hashlib,math,csv,io
from datetime import datetime,timezone
import numpy as np

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def build_packet(panel,t,small,case,named=False):
 ds=panel['dates'];names=panel['symbols'];entries=[];mapping={}
 for symbol in names:
  c=np.asarray(panel['series'][symbol]['close'][t-252:t+1],dtype=float);v=np.asarray(panel['series'][symbol]['volume'][t-252:t+1],dtype=float)
  if len(c)!=253 or not np.isfinite(c).all() or not np.isfinite(v).all() or (c<=0).any() or (v<=0).any():continue
  r=c[1:]/c[:-1]-1
  features=[100*(c[-1]/c[-6]-1),100*(c[-1]/c[-22]-1),100*(c[-1]/c[-64]-1),100*(c[-22]/c[-127]-1),100*(c[-22]/c[0]-1),100*r[-21:].std(ddof=1),100*r[-63:].std(ddof=1),100*(c[-1]/c[-63:].max()-1),v[-5:].mean()/v[-63:].mean(),float(np.log((c[-21:]*v[-21:]).mean()))]
  ordering=hashlib.sha256(f'astra-capsule-v1:{case}:{symbol}'.encode()).hexdigest();entries.append((ordering,symbol,features))
 entries.sort();buf=io.StringIO();w=csv.writer(buf,lineterminator='\n');w.writerow(['id','in100','return5_pct','return21_pct','return63_pct','momentum126_skip21_pct','momentum252_skip21_pct','dailyvol21_pct','dailyvol63_pct','drawdown63_pct','volume5_over63','log_dollarvolume21'])
 for i,(_,s,f) in enumerate(entries):
  identity=s if named else f'S{i+1:03d}';mapping[identity]=s;w.writerow([identity,int(s in small),*[round(x,3) for x in f]])
 market=np.array(panel['series']['SPY']['close'][t-252:t+1],dtype=float);mr=market[1:]/market[:-1]-1
 marketfacts={f'return{k}_pct':round(float((market[-1]/market[-k-1]-1)*100),3) for k in [5,21,63,252]};marketfacts['dailyvol21_pct']=round(float(mr[-21:].std(ddof=1)*100),3)
 nsmall=sum(s in small for _,s,_ in entries)
 packet={'case_id':case,'cutoff':ds[t] if named else 'End of the supplied observed session; date deliberately blinded',
 'task':'Choose two long-only equal-weight portfolios for the next21 trading sessions, using only supplied evidence. This is a retrospective test, not an order.',
 'universe_counts':{'diverse100_eligible':nsmall,'sp500_eligible':len(entries)},'required_selections':{'diverse100':math.ceil(nsmall/3),'sp500':math.ceil(len(entries)/3)},
 'market_past_only':marketfacts,'columns':'Returns/momentum/drawdown in percent; dailyvol is past daily simple-return sample standard deviation in percent. Momentum skips most recent21sessions. Volume ratio is last5 average/last63. Logdollarvolume is natural log of past21 mean close*volume. in100=1 identifies the sector-balanced subset. Higher predicted return is preferred. Data is current-revised adjusted history, not a historical vintage.',
 'evidence_csv':buf.getvalue(),'rules':['Do not cheat. There is no value in using hindsight. Use only thispacket.','Do not browse, search, read memory, otherproject files, otherpackets or any benchmark outcomes. No external/model tools, agents or network.','Do not infer hidden stock identities/dates or exploit recalled later outcomes. If recognizable history intrudes, record it and do not use it.','You may reason or run local numeric calculations using only thispacket. Do not use anyexisting model predictions or strategycode.','Make independent current decisions, freeze once, no future-feedback revisions. Choose exactly the requiredcounts, uniqueIDs. diverse100 only in100=1. sp500 mayuseanysuppliedID.','Return a short evidence-based rationale and an honest disclosure of any remembered future information; a no-hindsight promise is not proof that contamination is absent.']}
 return packet,mapping

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--source',type=Path,required=True);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();root=a.output;root.mkdir(parents=True,exist_ok=False)
 for folder in ['packets','decisions','private','code']: (root/folder).mkdir()
 panelpath=a.source/'panel-sp500-quality.json';panel=json.loads(panelpath.read_text());small=set(json.loads((a.source/'universe.json').read_text())['diverse100_symbols']);ds=panel['dates'];first=ds.index('2021-09-03');end=ds.index('2026-09-04');origins=list(range(first,end-1,21));named_indices=[0,12,24,36,48,59]
 protocol={'declared_at':datetime.now(timezone.utc).isoformat(),'model':'gpt-6-astra','design':'60 fresh-context blinded decisionagents, onecutoffeach, sameagentchoosesbothuniverses;6 fresh named pairedcontrols','model_setting':'explicitAstra; inherited default reasoning; no future-feedback revisions','source_panel_sha256':sha(panelpath),'source_universe_sha256':sha(a.source/'universe.json'),'first_entry':'2021-09-07','final_liquidation':'2026-09-04','models_compared':['Astra blindselector','fixedRidge','fixedHGB','momentum','equalweight','SPY','cash'],
 'rules':'topthirdceil;equalweight;21sessionrebalance; finalpartialholdliquidatefixeddate;cost11/22bps;no leverage','input':'past-only10rawnumericfeaturesrounded3decimal, pastmarketreturns/vol; no strategyresults, no futureprices, no companynews/fundamentals','named_control_cases':named_indices,
 'isolation':'fork_turns=none; per-casepacketaccess-only instructions. Sharedfilesystem is not an OS-enforcedsecurityboundary. Learnedmodelknowledge cannotbeerased. Tooluse is auditable but self-attestations cannot prove purity.',
 'limits':['This tests supplied price/volume decision-making, not unrestricted companyresearch','Current-roster survivorship and revisedprices inherited; historicalmembership notqualified','Namedpairedcontrols onlysixperiods, not afiveyearnamedportfolio','Sameunderlyingmodel; casesnotindependent replicas ofdifferentAImodels','No promisedfutureprofitability; noorders orpaperschedulechanges','LLMdeliberation variable; exactoutput hash retained; no secondtry basedonperformance']}
 (root/'protocol.json').write_text(json.dumps(protocol,indent=2)+'\n');cases=[]
 for k,t in enumerate(origins):
  for named in [False,True] if k in named_indices else [False]:
   case=f'{"named" if named else "blind"}-{k:03d}';packet,mapping=build_packet(panel,t,small,case,named)
   path=root/'packets'/f'{case}.json';path.write_text(json.dumps(packet,indent=2)+'\n')
   cases.append({'case_id':case,'named':named,'origin_index':t,'entry_index':t+1,'exit_index':min(t+22,end),'truncated':t+22>end,'date':ds[t],'packet_sha256':sha(path),'id_to_symbol':mapping,'required_selections':packet['required_selections']})
 (root/'private/cases.json').write_text(json.dumps(cases,indent=2)+'\n')
 print(json.dumps({'cases':len(cases),'main_cases':len(origins),'packet_bytes':sum(p.stat().st_size for p in (root/'packets').glob('*.json'))}))
if __name__=='__main__':main()
