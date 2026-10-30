"""Validate and freeze Astra choices before replaying any future portfolio prices."""
from pathlib import Path
from datetime import datetime, timezone
import argparse,csv,io,json,hashlib,math,sys
import numpy as np
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from scripts.research.prediction_wide_portfolios import simulate,validate_rows
from scripts.research.prediction_portfolios import circular_mean_interval
from scripts.research.verify_prediction_wide import replay

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.write_text(json.dumps(x,indent=2,allow_nan=False)+'\n')
def validate(root,case):
    cid=case['case_id'];packet_path=root/'packets'/f'{cid}.json';path=root/'decisions'/f'{cid}.json'
    assert sha(packet_path)==case['packet_sha256'],f'{cid}: packet changed'
    packet=json.loads(packet_path.read_text());d=json.loads(path.read_text());assert d['case_id']==cid
    evidence=list(csv.DictReader(io.StringIO(packet['evidence_csv'])));allids={r['id'] for r in evidence};small={r['id'] for r in evidence if r['in100']=='1'}
    assert allids==set(case['id_to_symbol'])
    for universe,allowed in [('diverse100',small),('sp500',allids)]:
        selected=d[universe]['selected_ids'];assert isinstance(selected,list) and all(isinstance(x,str) for x in selected)
        assert len(selected)==len(set(selected))==packet['required_selections'][universe],f'{cid}/{universe}: incorrect unique selection count'
        assert set(selected)<=allowed,f'{cid}/{universe}: invalid membership'
        assert d[universe]['confidence'] in ['low','medium','high'];assert isinstance(d[universe]['rationale'],str) and d[universe]['rationale'].strip()
    for field in ['method_summary','hindsight_disclosure','evidence_boundary_attestation']:
        assert isinstance(d[field],str) and d[field].strip(),f'{cid}: missing {field}'
    assert isinstance(d['limitations'],list) and d['limitations']
    return d

def status(root,cases):
    valid=[];errors=[];missing=[]
    for c in cases:
        if not (root/'decisions'/f"{c['case_id']}.json").exists():missing.append(c['case_id']);continue
        try:validate(root,c);valid.append(c['case_id'])
        except Exception as e:errors.append({'case_id':c['case_id'],'error':str(e)})
    result={'valid':len(valid),'main_valid':sum(x.startswith('blind') for x in valid),'named_valid':sum(x.startswith('named') for x in valid),'errors':errors,'missing':missing}
    write(root/'decision-validation.json',result);return result

def freeze(root,cases):
    state=status(root,cases);assert not state['missing'] and not state['errors'],state
    path=root/'decisions-frozen.json';assert not path.exists(),'Already frozen; do not overwrite'
    audit=json.loads((root/'access-audit.json').read_text()); agents={x['case_id']:x for x in audit['agents']}
    assert set(agents)=={c['case_id'] for c in cases},'Missing agent access records'
    assert not audit['flagged_cases'],'Review access flags before freezing'
    assert all(x['model_contexts'] and all(v['model']=='gpt-6-astra' for v in x['model_contexts']) for x in agents.values())
    spawns=json.loads((root/'spawn-receipts.json').read_text())['requests']
    assert len(spawns)==len(cases) and {x['request']['task_name'] for x in spawns}=={'astra_'+c['case_id'].replace('-','_') for c in cases}
    assert all(x['request']['fork_turns']=='none' and x['request']['model']=='gpt-6-astra' for x in spawns)
    receipt={'context_limitations_sha256':sha(root/'context-limitations.json'),'spawn_receipts_sha256':sha(root/'spawn-receipts.json'),'access_audit_sha256':sha(root/'access-audit.json'),'frozen_at':datetime.now(timezone.utc).isoformat(),'protocol_sha256':sha(root/'protocol.json'),'contract_sha256':sha(root/'decision-contract.txt'),'private_cases_sha256':sha(root/'private/cases.json'),'decision_count':len(cases),'model_requested':'gpt-6-astra','fork_turns':'none','records':[]}
    for c in cases:
        cid=c['case_id'];receipt['records'].append({'case_id':cid,'agent_task':agents[cid]['agent_task'],'agent_id':agents[cid]['agent_id'],'model_contexts':agents[cid]['model_contexts'],'packet_sha256':c['packet_sha256'],'decision_sha256':sha(root/'decisions'/f'{cid}.json')})
    write(path,receipt);return receipt

def rows_for(panel,cases,decisions,universe):
    rows=[]
    for c in cases:
        d=decisions[c['case_id']];mapping=c['id_to_symbol'];selected={mapping[i] for i in d[universe]['selected_ids']};eligible=[s for s in panel['symbols'] if s in set(mapping.values())]
        assert selected<=set(eligible) and len(selected)==math.ceil(len(eligible)/3)
        rows.append({**{k:c[k] for k in ['origin_index','entry_index','exit_index','truncated','date']},'eligible_symbols':eligible,'scores':{'astra':[int(s in selected) for s in eligible]},'case_id':c['case_id']})
    return rows

def compare_recursive(a,b,path=''):
    if isinstance(a,dict):
        for k,v in a.items():compare_recursive(v,b[k],path+'.'+k)
    elif isinstance(a,list):
        assert len(a)==len(b),path
        for i,(x,y) in enumerate(zip(a,b)):compare_recursive(x,y,path+f'[{i}]')
    elif isinstance(a,(int,float)) and not isinstance(a,bool):assert b is not None and math.isclose(a,b,rel_tol=1e-8,abs_tol=1e-10),(path,a,b)
    else:assert a==b,(path,a,b)

def score(root,source,cases):
    receipt=json.loads((root/'decisions-frozen.json').read_text());assert receipt['protocol_sha256']==sha(root/'protocol.json');assert receipt['private_cases_sha256']==sha(root/'private/cases.json');assert receipt['contract_sha256']==sha(root/'decision-contract.txt')
    assert receipt['access_audit_sha256']==sha(root/'access-audit.json')
    assert receipt['context_limitations_sha256']==sha(root/'context-limitations.json')
    assert receipt['spawn_receipts_sha256']==sha(root/'spawn-receipts.json')
    decisions={c['case_id']:validate(root,c) for c in cases}
    for record in receipt['records']:assert record['decision_sha256']==sha(root/'decisions'/f"{record['case_id']}.json")
    main=[c for c in cases if not c['named']];named=[c for c in cases if c['named']];assert len(main)==60 and len(named)==6
    result={'frozen_decisions_sha256':sha(root/'decisions-frozen.json'),'scored_at':datetime.now(timezone.utc).isoformat(),'universes':{},'named_pairs':[],'verification':[]}
    for universe in ['diverse100','sp500']:
        panelpath=source/f'panel-{universe}-quality.json';panel=json.loads(panelpath.read_text());quant=json.loads((source/f'{universe}-quality/portfolios/portfolios.json').read_text());original=json.loads((source/f'{universe}-quality/ranking/predictions.json').read_text());rows=rows_for(panel,main,decisions,universe)
        assert sha(panelpath)==original['metadata']['panel_sha256']
        for a,b in zip(rows,original['rows']):
            for k in ['origin_index','entry_index','exit_index','truncated','eligible_symbols']:assert a[k]==b[k],(universe,k)
        validate_rows(panel,{'metadata':original['metadata'],'rows':rows,'failures':[]})
        # Persist translated stock decisions before portfolio simulation.
        write(root/f'predictions-{universe}.json',{'rows':rows,'metadata':original['metadata'],'failures':[],'frozen_decisions_sha256':result['frozen_decisions_sha256']})
        overlap={}
        for model in ['ridge','hgb','momentum_12_1']:
            fractions=[]
            for ar,qr in zip(rows,original['rows']):
                selected={symbol for symbol,v in zip(ar['eligible_symbols'],ar['scores']['astra']) if v}
                k=len(selected); positions={symbol:i for i,symbol in enumerate(panel['symbols'])}
                ordered=sorted(zip(qr['eligible_symbols'],qr['scores'][model]),key=lambda x:(-x[1],positions[x[0]]))
                other={symbol for symbol,_ in ordered[:k]}; fractions.append(len(selected&other)/k)
            overlap[model]={'mean_selected_overlap_fraction':float(np.mean(fractions)),'min':min(fractions),'max':max(fractions),'per_origin':fractions}
        costs={};full=np.array([not r['truncated'] for r in rows])
        for cost in [11,22]:
            p=simulate(panel,rows,'astra',cost/10000);independent=replay(panel,rows,'astra',cost/10000);compare_recursive(independent,p)
            result['verification'].append({'universe':universe,'cost_bps':cost,'independent_accounting':'passed'})
            if p['state']=='complete':
                for control in ['ridge','hgb','momentum_12_1','equal_weight','SPY']:
                    b=quant['costs'][str(cost)][control]
                    assert b['state']=='complete'
                    p['paired_period_excess_vs_'+control]=circular_mean_interval((np.array(p['period_returns'])-b['period_returns'])[full],3)
                spy=quant['costs'][str(cost)]['SPY']
                if not p['valuation_gaps'] and not spy['valuation_gaps']:
                    dr=np.array(p['daily_returns']);market=np.array(spy['daily_returns']);p['beta_to_SPY']=float(np.cov(dr,market,ddof=1)[0,1]/market.var(ddof=1))
            costs[str(cost)]={'astra':p,**quant['costs'][str(cost)]}
        result['universes'][universe]={'costs':costs,'decision_overlap':overlap,'panel_sha256':sha(panelpath),'comparison_sha256':sha(source/f'{universe}-quality/portfolios/portfolios.json')}
        # Paired controls are isolated round-trip holds, never stitched across gaps.
        for c in named:
            blind=next(x for x in main if x['origin_index']==c['origin_index']);nrow=rows_for(panel,[c],decisions,universe);brow=rows_for(panel,[blind],decisions,universe)
            ns={c['id_to_symbol'][i] for i in decisions[c['case_id']][universe]['selected_ids']};bs={blind['id_to_symbol'][i] for i in decisions[blind['case_id']][universe]['selected_ids']}
            pair={'universe':universe,'date':c['date'],'named_case':c['case_id'],'blind_case':blind['case_id'],'truncated':c['truncated'],'overlap_fraction':len(ns&bs)/len(ns),'jaccard':len(ns&bs)/len(ns|bs),'costs':{}}
            for cost in [11,22]:
                outcomes={}
                for mode,r in [('named',nrow),('blind',brow)]:
                    sim=simulate(panel,r,'astra',cost/10000);audit=replay(panel,r,'astra',cost/10000);compare_recursive(audit,sim)
                    outcomes[mode]={k:sim[k] for k in ['state','net_return','valuation_gaps'] if k in sim}
                pair['costs'][str(cost)]=outcomes
            result['named_pairs'].append(pair)
    write(root/'results.json',result);return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['status','freeze','score']);ap.add_argument('--root',type=Path,required=True);ap.add_argument('--source',type=Path);a=ap.parse_args();cases=json.loads((a.root/'private/cases.json').read_text())
    if a.action=='status':print(json.dumps(status(a.root,cases)))
    elif a.action=='freeze':print(json.dumps({'frozen':freeze(a.root,cases)['decision_count']}))
    else:
        result=score(a.root,a.source,cases);print(json.dumps({u:{cost:{m:{k:p.get(k) for k in ['state','net_return','cagr','max_drawdown']} for m,p in v.items()} for cost,v in r['costs'].items()} for u,r in result['universes'].items()}))
if __name__=='__main__':main()
