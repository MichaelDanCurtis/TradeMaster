"""Create one prospective HGB/buffer research decision from a new closed panel.

No data fetching, outcomes, broker orders, or scheduler changes. The caller must
supply a fresh price panel with closed_through and captured_at metadata.
"""
import argparse,json,hashlib
from pathlib import Path
from datetime import datetime,time,timezone
from zoneinfo import ZoneInfo
from scripts.research.prediction_wide_ranking import Panel
from scripts.research.run_prediction_improvements import predict
from scripts.research.prediction_improvement_targets import choose

def validate_forward_panel(panel,decision_date,now=None):
    now=now or datetime.now(timezone.utc)
    if decision_date<'2026-09-08':raise ValueError('This study starts after the already examined historical interval')
    if panel.get('closed_through')!=decision_date:raise ValueError('Fresh panel must explicitly confirm its last fully closed session')
    if panel['dates'][-1]!=decision_date:raise ValueError('Only information through the decision session may enter the forward panel')
    decision_close=datetime.combine(datetime.fromisoformat(decision_date).date(),time(16,15),ZoneInfo('America/New_York'))
    captured=datetime.fromisoformat(panel['captured_at'].replace('Z','+00:00'))
    if captured.tzinfo is None or captured<decision_close or captured>now or now<decision_close:raise ValueError('A future or not-yet-closed session cannot be forecast as observed data')

def forecast(panel,decision_date,previous=(),now=None):
    validate_forward_panel(panel,decision_date,now);data=Panel(panel);t=len(data.dates)-1;ix,features,_,_=data.features(t)
    if features is None:raise ValueError('Insufficient eligible price histories')
    template={'metadata':{'symbols':data.symbols,'benchmark':panel['benchmark']},'rows':[{'origin_index':t,'date':decision_date,'eligible_symbols':[data.symbols[i] for i in ix]}]}
    row=predict(panel,template)['rows'][0];ordinary=choose(row['eligible_symbols'],row['scores']['hgb']);buffered=choose(row['eligible_symbols'],row['scores']['hgb'],previous,True)
    return {'state':'forecast_frozen_without_outcomes','decision_date':decision_date,'entry':'next regular-session open','holding_horizon_sessions':21,'candidate':'hgb_buffer','benchmark':panel['benchmark'],'eligible_symbols':row['eligible_symbols'],'scores':row['scores']['hgb'],'baseline_selected':ordinary,'candidate_selected':buffered,'weight_each':1/len(buffered),'last_training_exit_index':row['last_training_exit_index'],'training_row_count':row['training_row_count'],'previous_selected':list(previous),'scope':'Prospective research decision only. Does not assert fills or complete corporate-action accounting.'}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--panel',type=Path,required=True);ap.add_argument('--date',required=True);ap.add_argument('--previous',type=Path);ap.add_argument('--output',type=Path,required=True);a=ap.parse_args();assert not a.output.exists(),'Do not overwrite a frozen forward decision';panel=json.loads(a.panel.read_text());prior=json.loads(a.previous.read_text()) if a.previous else None
    if prior is not None and prior['decision_date']>=a.date:raise ValueError('Previous decision must strictly precede the new cutoff')
    previous=prior['candidate_selected'] if prior else [];result=forecast(panel,a.date,previous);result['panel_sha256']=hashlib.sha256(a.panel.read_bytes()).hexdigest();result['previous_sha256']=hashlib.sha256(a.previous.read_bytes()).hexdigest() if a.previous else None;result['created_at']=datetime.now(timezone.utc).isoformat();a.output.parent.mkdir(exist_ok=True,parents=True);a.output.write_text(json.dumps(result,indent=2,allow_nan=False)+'\n');print(a.output)
if __name__=='__main__':main()
