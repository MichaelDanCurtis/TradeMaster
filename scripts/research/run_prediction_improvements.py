"""Fit frozen fundamental challenger, freeze target portfolios, then score."""
import argparse,json,hashlib,math
from datetime import datetime,timezone
from pathlib import Path
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor
from scripts.research.prediction_wide_ranking import Panel
from scripts.research.prediction_fundamentals import rank_observed
from scripts.research.prediction_improvement_targets import plan
from scripts.research.prediction_wide_portfolios import simulate
from scripts.research.verify_prediction_wide import replay
from scripts.research.prediction_portfolios import circular_mean_interval
from scripts.research.evaluate_astra_capsules import compare_recursive

VARIANTS=['hgb','hgb_buffer','hgb_buffer_risk','hgb_fundamentals','hgb_fundamentals_buffer_risk']
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def model():return HistGradientBoostingRegressor(loss='squared_error',max_iter=100,learning_rate=.03,max_depth=2,max_leaf_nodes=4,min_samples_leaf=50,l2_regularization=1,early_stopping=False,random_state=59137)

def predict(panel,original,fund=None):
    data=Panel(panel);positions={s:i for i,s in enumerate(fund['symbols'])} if fund is not None else {};fund_origins={int(t):i for i,t in enumerate(fund['origins'])} if fund is not None else {};feature_cache={};train_cache={}
    def features(t):
        if t in feature_cache:return feature_cache[t]
        ix,x,m,info=data.features(t)
        if x is not None and fund is not None:
            raw=fund['values'][fund_origins[t]][[positions[data.symbols[j]] for j in ix]];x=np.column_stack([x,rank_observed(raw)])
        feature_cache[t]=(ix,x);return ix,x
    rows=[]
    for k,template in enumerate(original['rows']):
        t=template['origin_index'];ix,x=features(t);assert [data.symbols[j] for j in ix]==template['eligible_symbols'];mature=list(range(252,t-22+1,21));usable=[]
        for o in mature:
            if o not in train_cache:
                j,z=features(o)
                if z is None:train_cache[o]=None;continue
                endpoints=data.arrays['open'][[o+1,o+22]][:,j];valid=np.isfinite(endpoints).all(axis=0)&(endpoints>0).all(axis=0)
                if valid.sum()<2:train_cache[o]=None;continue
                y=endpoints[1,valid]/endpoints[0,valid]-1;y-=y.mean();train_cache[o]=(z[valid],y)
            if train_cache[o] is not None:usable.append(o)
        assert len(usable)>=24 and max(usable)+22<=t
        training_x=np.concatenate([train_cache[o][0] for o in usable]);training_y=np.concatenate([train_cache[o][1] for o in usable]);fitted=model().fit(training_x,training_y);pred=fitted.predict(x);assert np.isfinite(pred).all()
        rows.append({**template,'scores':{'hgb':pred.tolist()},'training_row_count':len(training_x),'training_origin_count':len(usable),'last_training_exit_index':max(usable)+22})
        if (k+1)%10==0:print('Predictions',len(data.symbols),'stocks',k+1,'/',len(original['rows']),flush=True)
    return {'metadata':{**original['metadata'],'model':'frozen HGB with eight filing-date-bounded annual features' if fund is not None else 'frozen HGB historical membership diagnostic','features_added':list(fund['features']) if fund is not None else []},'rows':rows,'failures':[]}

def templates(panel):
    data=Panel(panel);first=data.dates.index('2021-09-03');end=data.dates.index('2026-09-04');rows=[]
    for t in range(first,end-1,21):
        ix,x,m,info=data.features(t);rows.append({'origin_index':t,'date':data.dates[t],'entry_index':t+1,'exit_index':min(t+22,end),'truncated':t+22>end,'eligible_symbols':[data.symbols[j] for j in ix]})
    return {'metadata':{'symbols':data.symbols,'benchmark':panel['benchmark']},'rows':rows}

def prediction_stage(root,source):
    assert not (root/'targets-frozen.json').exists()
    with np.load(root/'fundamentals.npz',allow_pickle=False) as archive:fund={k:archive[k] for k in archive.files}
    for universe in ['diverse100','sp500']:
        target=root/f'{universe}-fundamental-predictions.json'
        if target.exists():raise ValueError('Do not overwrite completed predictions')
        panelpath=source/f'panel-{universe}-quality.json';panel=json.loads(panelpath.read_text());basepath=source/f'{universe}-quality/ranking/predictions.json';original=json.loads(basepath.read_text());assert original['metadata']['panel_sha256']==sha(panelpath)
        pred=predict(panel,original,fund);pred['inputs']={'panel_sha256':sha(panelpath),'original_predictions_sha256':sha(basepath),'fundamentals_sha256':sha(root/'fundamentals.npz'),'protocol_sha256':sha(root/'protocol.json')};write(target,pred)
    panelpath=root/'historical/panel.json';panel=json.loads(panelpath.read_text());pred=predict(panel,templates(panel));pred['inputs']={'panel_sha256':sha(panelpath),'protocol_sha256':sha(root/'protocol.json')};write(root/'historical/predictions.json',pred)

def plan_stage(root,source):
    assert not (root/'targets-frozen.json').exists();files=[]
    for universe in ['diverse100','sp500']:
        panel=json.loads((source/f'panel-{universe}-quality.json').read_text());base=source/f'{universe}-quality/ranking/predictions.json';fund=root/f'{universe}-fundamental-predictions.json'
        for variant in VARIANTS:
            path=fund if 'fundamentals' in variant else base;pred=json.loads(path.read_text());rows=plan(panel,pred['rows'],variant);output=root/f'{universe}-{variant}-targets.json';assert not output.exists()
            write(output,{'variant':variant,'rows':rows,'predictions_sha256':sha(path),'protocol_sha256':sha(root/'protocol.json')});files.append(output)
    historical=root/'historical/predictions.json';files += [historical,root/'historical/panel.json',root/'fundamentals.npz',root/'fundamentals-coverage.json']
    files += [root/f'{u}-fundamental-predictions.json' for u in ['diverse100','sp500']]
    write(root/'targets-frozen.json',{'frozen_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':sha(root/'protocol.json'),'files':{str(p.relative_to(root)):sha(p) for p in files},'source_code':{p.name:sha(p) for p in [Path(__file__),Path(__file__).with_name('prediction_improvement_targets.py'),Path(__file__).with_name('prediction_fundamentals.py')]}})
    print('Frozen all variant targets and historical predictions before scoring',flush=True)

def score_stage(root,source):
    frozen=json.loads((root/'targets-frozen.json').read_text());assert frozen['protocol_sha256']==sha(root/'protocol.json');assert all(sha(root/k)==v for k,v in frozen['files'].items());result={'scored_at':datetime.now(timezone.utc).isoformat(),'frozen_targets_sha256':sha(root/'targets-frozen.json'),'universes':{},'audits':[]}
    for universe in ['diverse100','sp500']:
        panel=json.loads((source/f'panel-{universe}-quality.json').read_text());reference=json.loads((source/f'{universe}-quality/portfolios/portfolios.json').read_text());costs={}
        for cost in [11,22]:
            outputs={}
            for variant in VARIANTS:
                rows=json.loads((root/f'{universe}-{variant}-targets.json').read_text())['rows'];p=simulate(panel,rows,'frozen_target',cost/10000);audit=replay(panel,rows,'frozen_target',cost/10000);compare_recursive(audit,p)
                if variant=='hgb':
                    old=reference['costs'][str(cost)]['hgb'];assert p['state']==old['state']
                    for metric in ['net_return','cagr','max_drawdown','two_sided_turnover_sum']:assert math.isclose(p[metric],old[metric],rel_tol=1e-9,abs_tol=1e-10),(universe,metric)
                outputs[variant]=p;result['audits'].append({'universe':universe,'variant':variant,'cost':cost,'independent_replay':'passed'})
                print('Scored',universe,variant,cost,'bps',p['state'],flush=True)
            outputs['SPY']=reference['costs'][str(cost)]['SPY'];full=np.array([not r['truncated'] for r in rows])
            for variant,p in outputs.items():
                if p['state']!='complete':continue
                for control in ['hgb','SPY']:
                    b=outputs[control]
                    if b['state']=='complete':p['paired_period_excess_vs_'+control]=circular_mean_interval((np.array(p['period_returns'])-b['period_returns'])[full],3)
                market=outputs['SPY']
                if not p['valuation_gaps']:
                    dr=np.asarray(p['daily_returns']);mr=np.asarray(market['daily_returns']);p['beta_to_SPY']=float(np.cov(dr,mr,ddof=1)[0,1]/mr.var(ddof=1))
            costs[str(cost)]=outputs
        result['universes'][universe]={'costs':costs}
    panel=json.loads((root/'historical/panel.json').read_text());pred=json.loads((root/'historical/predictions.json').read_text());historical={}
    for cost in [11,22]:
        p=simulate(panel,pred['rows'],'hgb',cost/10000);audit=replay(panel,pred['rows'],'hgb',cost/10000);compare_recursive(audit,p);historical[str(cost)]=p
    result['historical_membership_diagnostic']={'qualification':'Unqualified: community reconstruction, historical identity/sector and terminal corporate-action gaps retained','costs':historical};write(root/'results.json',result)
    print(json.dumps({u:{k:round(v.get('cagr',0)*100,2) for k,v in x['costs']['11'].items()} for u,x in result['universes'].items()}));print('Historical',[(k,v['state'],v.get('date'),v.get('unresolved_symbols')) for k,v in historical.items()])

def main():
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['predict','plan','score']);ap.add_argument('--root',type=Path,required=True);a=ap.parse_args();source=Path(json.loads((a.root/'protocol.json').read_text())['source']);{'predict':prediction_stage,'plan':plan_stage,'score':score_stage}[a.stage](a.root,source)
if __name__=='__main__':main()
