"""Separate correction of a documented current-security inception boundary."""
import argparse,copy
from pathlib import Path
from datetime import datetime,timezone
from scripts.research.validate_prediction_history import read,write,sha,frozen_targets
from scripts.research.prediction_wide_ranking import Panel
from scripts.research.run_prediction_improvements import predict
from scripts.research.prediction_event_accounting import simulate_events
from scripts.research.reconcile_prediction_history import prepare_events
from scripts.research.evaluate_astra_capsules import compare_recursive


def inception(panel,symbol,first_session):
    p=copy.deepcopy(panel)
    for i,d in enumerate(p['dates']):
        if d<first_session:
            for values in p['series'][symbol].values():values[i]=None
    return p


def main(r):
    dst=r/'identity-sensitivity';dst.mkdir(exist_ok=False)
    write(dst/'protocol.json',{'created_at':datetime.now(timezone.utc).isoformat(),'symbol':'EXE','first_new_common_session':'2021-02-10','first_session_source_url':'https://investors.expandenergy.com/news-releases/news-release-details/chesapeake-energy-corporation-successfully-emerges-financial','first_session_source_access':'Official issuer page read through web tool; raw page capture attempted separately. SEC cancellation filing archived.',
          'source_sha256':sha(r/'event-sources/chk-cancellation-sec.html'),'rule':'Current-security history cannot include cancelled predecessor equity. Set all earlier EXE observations to missing; preserve every other observation and original historical-membership panel. Retrain both unchanged models on corrected inputs before scoring.',
          'scope':'Post-diagnostic data correction, not untouched validation. Existing frozen forecasts/results are retained.',
          'code_sha256':sha(Path(__file__))})
    prepared={};files=[]
    for u in ['diverse100','sp500']:
        p=inception(read(r/f'{u}-early-panel.json'),'EXE','2021-02-10');write(dst/f'{u}-panel.json',p);old=read(r/f'{u}-early-predictions.json');data=Panel(p);rows=[]
        for row in old['rows']:
            indices,features,_,_=data.features(row['origin_index']);rows.append({**row,'eligible_symbols':[p['symbols'][i] for i in indices]})
        pred=predict(p,{'metadata':old['metadata'],'rows':rows});path=dst/f'{u}-predictions.json';write(path,pred);files.append(path)
        targets={}
        for v in ['hgb','hgb_buffer']:
            targets[v]=frozen_targets(p,pred,v=='hgb_buffer');path=dst/f'{u}-{v}-targets.json';write(path,targets[v]);files.append(path)
        valuation,events=prepare_events(r,p,'early');write(dst/f'{u}-valuation.json',valuation);prepared[u]=(valuation,events,targets)
    write(dst/'targets-lock.json',{'locked_at':datetime.now(timezone.utc).isoformat(),'files':{p.name:sha(p) for p in files}})
    result={}
    for u,(p,events,targets) in prepared.items():
        costs={}
        for bps in [11,22]:
            models={}
            for v in ['hgb','hgb_buffer','SPY']:
                rows=copy.deepcopy(targets[v if v!='SPY' else 'hgb'])
                if v=='SPY':
                    row=rows[0];row['exit_index']=rows[-1]['exit_index'];row['target_weights']=[0.]*len(p['symbols'])+[1.];rows=[row]
                a=simulate_events(p,rows,events,bps/10000);b=simulate_events(p,rows,events,bps/10000,True);compare_recursive(a,b);models[v]=a
                print(u,bps,v,a['state'],a.get('cagr'),a.get('unresolved_symbols'),flush=True)
            costs[str(bps)]=models
        result[u]=costs
    write(dst/'results.json',result)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);main(ap.parse_args().root)
