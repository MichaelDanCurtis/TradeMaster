"""Frozen, read-only forward research: archive inputs, forecast before entry, observe.

Run tick with the application venv. It invokes finish in the numerical venv.
No broker orders or account mutations. Market opens are research marks, not fills.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
HERE = Path(__file__).resolve().parents[2]
FIRST = '2026-09-08'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, value, exclusive=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, allow_nan=False) + '\n'
    if exclusive:
        with path.open('x') as f:
            f.write(text)
    else:
        tmp = path.with_suffix('.tmp')
        tmp.write_text(text)
        tmp.replace(path)


def instant(day, hhmm):
    return datetime.fromisoformat(day + 'T' + hhmm).replace(tzinfo=NY)


def schedule(calendar, first=FIRST, periods=12):
    dates = [x['date'] for x in calendar]
    if dates != sorted(set(dates)):
        raise ValueError('Calendar must have unique ordered sessions')
    start = dates.index(first)
    out = []
    for n in range(periods):
        i = start + 21*n
        if i+22 >= len(dates):
            raise ValueError('Calendar does not cover the declared study horizon')
        entry = calendar[i+1]
        out.append({'number': n, 'decision_date': dates[i], 'entry_date': entry['date'],
                    'entry_open': instant(entry['date'], entry['open']).isoformat(),
                    'freeze_deadline': (instant(entry['date'], entry['open'])-timedelta(minutes=5)).isoformat(),
                    'exit_date': dates[i+22]})
    return out


def window(plan, now):
    ready = instant(plan['decision_date'], '16:15')
    if now < ready:
        return 'waiting_for_close'
    if now >= datetime.fromisoformat(plan['freeze_deadline']):
        return 'missed_deadline'
    return 'ready'


def verify_protocol(root):
    freeze = read(root/'protocol-lock.json')
    if sha(root/'protocol.json') != freeze['protocol_sha256']:
        raise ValueError('Frozen study protocol changed')
    p = read(root/'protocol.json')
    for name, expected in p['code_sha256'].items():
        if sha(HERE/name) != expected:
            raise ValueError('Frozen research code changed: '+name)
    for name, expected in p['input_sha256'].items():
        if sha(root/name) != expected:
            raise ValueError('Frozen study input changed: '+name)
    return p


def services(target):
    from scripts.research.capture_prediction_improvements import Capture, provider
    from dotenv import load_dotenv
    from tradingagents.ui.db import create_session_factory
    from tradingagents.research.deployment_cycle_child import resolve_configured_broker
    load_dotenv('.env')
    headers, data_engine = provider()
    engine, sessions = create_session_factory('sqlite:///.tradingagents-ui.db')
    broker = resolve_configured_broker(sessions)
    target.mkdir(parents=True, exist_ok=True)
    market_dir = target/'market'; market_dir.mkdir(exist_ok=True)
    reference_dir = target/'reference'; reference_dir.mkdir(exist_ok=True)
    return Capture(market_dir, headers), Capture(reference_dir, broker._headers()), [engine, data_engine]


def required(capture, url, params, name):
    result = capture.get(url, params, name)
    if result is None:
        raise RuntimeError('Read-only capture failed: '+name)
    return result


def identities(roster, assets):
    by = {a['symbol']: a for a in assets}
    out = {}
    for symbol in roster:
        a = by.get(symbol)
        if not a or a.get('status') != 'active' or a.get('class') != 'us_equity' or not a.get('tradable'):
            raise ValueError('Unqualified current tradable identity: '+symbol)
        out[symbol] = {k: a.get(k) for k in ('id','symbol','name','class','exchange','status','tradable')}
    if len({a['id'] for a in out.values()}) != len(out):
        raise ValueError('Duplicate provider security identity')
    return out


def decision_files(root):
    files=sorted((root/'decisions').glob('*.json'))
    for path in files:
        if sha(path)!=read(root/'decision-locks'/path.name)['sha256']:
            raise ValueError('Frozen decision changed: '+path.name)
    return files


def prepare(root):
    if (root/'protocol-lock.json').exists():
        verify_protocol(root)
        print('Existing frozen forward study verified'); return
    if datetime.now(timezone.utc)>=instant(FIRST,'16:15'):
        raise ValueError('Initial roster and protocol must be frozen before the first decision cutoff')
    root.mkdir(parents=True, exist_ok=True)
    from scripts.research.prepare_prediction_universe import ConstituentsTable, capture
    inputs = root/'initial'; inputs.mkdir(exist_ok=True)
    sources = []
    if not (inputs/'roster-source.json').exists():
        raw = capture(inputs, 'wikipedia.html', 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', sources)
        parser = ConstituentsTable(); parser.feed(raw.decode())
        rows = parser.rows[1:]
        if not 490 <= len(rows) <= 520 or any(len(r)<7 for r in rows):
            raise ValueError('Unexpected constituent table')
        members = [{'symbol': r[0], 'name': r[1], 'sector': r[2], 'cik': r[6].zfill(10)} for r in rows]
        if len({r['symbol'] for r in members}) != len(members):
            raise ValueError('Duplicate roster symbols')
        save(inputs/'roster-source.json', {'members': members, 'sources': sources,
            'captured_at': datetime.now(timezone.utc).isoformat(),
            'scope': 'Community roster captured before first forward decision; fixed cohort, not continuously reconstituted S&P membership'}, True)
    roster = read(inputs/'roster-source.json')
    market, reference, engines = services(inputs)
    try:
        calendar = required(reference, 'https://paper-api.alpaca.markets/v2/calendar',
            {'start': '2016-01-01', 'end': '2027-11-30'}, 'calendar.json')
        assets = required(reference, 'https://paper-api.alpaca.markets/v2/assets',
            {'status': 'active', 'asset_class': 'us_equity'}, 'assets.json')
        names = [r['symbol'] for r in roster['members']]
        qualified = identities(names+['SPY'], assets)
        save(inputs/'identities.json', qualified)
        plan = schedule(calendar)
        files = ['scripts/research/'+name for name in (
            'prediction_forward_study.py','forecast_prediction_improvements.py','prediction_improvement_targets.py',
            'run_prediction_improvements.py','prediction_wide_ranking.py','prediction_ranking.py',
            'prediction_fundamentals.py','prediction_wide_portfolios.py','prediction_portfolios.py',
            'verify_prediction_wide.py','evaluate_astra_capsules.py','capture_prediction_improvements.py',
            'prepare_prediction_quality.py')]
        for name in files:
            dest = root/'code'/Path(name).name; dest.parent.mkdir(exist_ok=True)
            dest.write_bytes((HERE/name).read_bytes())
        protocol = {'created_at': datetime.now(timezone.utc).isoformat(), 'candidate': 'hgb_buffer',
            'controls': ['hgb','SPY'], 'universe': names, 'universe_policy': roster['scope'],
            'identity_rule': 'Provider asset IDs pinned; no automatic ticker substitution. Identity changes block forecasts and complete performance claims.',
            'parameters': {'rebalance_sessions':21,'selection':'ceil(eligible/3)','buffer_rank_fraction':.45,'buffer_score_advantage':.005,
                'cost_bps_per_side':[11,22],'leverage':False,'cash_interest':0,'taxes':'excluded'},
            'schedule': plan, 'checkpoints_sessions':[63,126,252],
            'missed_decision_rule':'No retrospective backfill. Record missed deadline and require review before continuing the study.',
            'comparison':'Same frozen HGB settings and expanding mature-label training; baseline and candidate differ only in holding selection.',
            'price_rule':'SIP daily bars, all-adjusted, asof pinned to roster capture date; fresh entire training history each decision, archived before next entry. Existing three historical quality masks retained.',
            'evidence_scope':'Shadow research, no broker fills. Adjusted-price diagnostics do not certify merger/delisting economics or complete corporate-action accounting.',
            'no_tuning':'Do not tune thresholds, select a winner or terminate on interim returns; observe all declared checkpoints.',
            'input_sha256':{str(p.relative_to(root)):sha(p) for p in inputs.rglob('*') if p.is_file()},
            'code_sha256':{name:sha(HERE/name) for name in files}}
        save(root/'protocol.json', protocol, True)
        save(root/'protocol-lock.json', {'protocol_sha256':sha(root/'protocol.json'),'locked_at':datetime.now(timezone.utc).isoformat()}, True)
        status(root, 'armed_waiting_for_first_close', first_decision=plan[0])
        print(json.dumps({'state':'armed_waiting_for_first_close','stocks':len(names),'first_decision':plan[0],'last_exit':plan[-1]['exit_date']}))
    finally:
        for e in engines: e.dispose()


def status(root, state, **details):
    value = {'state':state,'checked_at':datetime.now(timezone.utc).isoformat(),**details}
    save(root/'status.json', value)
    (root/'status.md').write_text('# Frozen forward comparison\n\n'+state.replace('_',' ')+'\n\n'+
        'Original HGB versus HGB with the replacement buffer, with SPY as the buy-and-hold control. Research observations only.\n\n'+
        '```json\n'+json.dumps(value,indent=2)+'\n```\n')
    print(json.dumps(value))


def build_panel(payloads, calendar, names, last, start, roster):
    dates = [r['date'] for r in calendar if start<=r['date']<=last]
    if not dates or dates[-1] != last:
        raise ValueError('Capture cutoff is not a calendar session')
    records = {s:{} for s in names+['SPY']}
    for payload in payloads:
        for symbol, bars in payload['bars'].items():
            if symbol not in records: raise ValueError('Unexpected symbol')
            for b in bars:
                day = datetime.fromisoformat(b['t'].replace('Z','+00:00')).astimezone(NY).date().isoformat()
                if day not in dates or day in records[symbol]: raise ValueError('Duplicate or out-of-window bar')
                values = [float(b[k]) for k in ('o','c','v')]
                if not all(math.isfinite(v) and v>=0 for v in values) or min(values[:2])<=0:
                    raise ValueError('Invalid price/volume')
                records[symbol][day] = [values[0] if values[2]>0 else None, values[1], values[2]]
    if last not in records['SPY']: raise ValueError('Benchmark cutoff missing')
    p = {'dates':dates,'symbols':names,'benchmark':'SPY',
         'series':{s:{f:[records[s].get(d,[None]*3)[i] for d in dates] for i,f in enumerate(('open','close','volume'))} for s in records},
         'sectors':{r['symbol']:r['sector'] for r in roster['members']},
         'issuers':{r['symbol']:r['cik'] for r in roster['members']},
         'closed_through':last,'captured_at':datetime.now(timezone.utc).isoformat(),
         'universe_scope':'Fixed cohort captured before first forward decision; no future-availability filtering'}
    if start=='2016-01-01':
        from scripts.research.prepare_prediction_quality import EVENTS
        for event in EVENTS:
            if event['symbol'] in names and event['date'] in dates:
                t=dates.index(event['date']); series=p['series'][event['symbol']];series['close'][t]=None
                for i in range(max(0,t-21),min(len(dates),t+22)):series['open'][i]=None
    return p


def tick(root):
    import fcntl
    root.mkdir(parents=True, exist_ok=True)
    with (root/'.tick.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: print('Another observation is running'); return
        _tick(root)


def _tick(root):
    p=verify_protocol(root); decision_files(root); now=datetime.now(timezone.utc)
    if (root/'observed'/(p['schedule'][-1]['exit_date']+'.json')).exists():
        status(root,'declared_horizon_observed_requires_assessment');return
    missing=next((r for r in p['schedule'] if not (root/'decisions'/(r['decision_date']+'.json')).exists()),None)
    if missing and window(missing,now)=='missed_deadline':
        missed=root/'missed'/(missing['decision_date']+'.json')
        if not missed.exists():save(missed,{'observed_at':now.isoformat(),'plan':missing,'state':'missed_no_backfill'},True)
        status(root,'needs_review_missed_decision',decision=missing);return
    if now < instant(FIRST,'16:15'):
        status(root,'armed_waiting_for_first_close',first_decision=p['schedule'][0]);return
    stamp=now.strftime('%Y%m%dT%H%M%S%fZ');run=root/'observations'/stamp
    market,reference,engines=services(run)
    try:
        calendar=required(reference,'https://paper-api.alpaca.markets/v2/calendar',{'start':'2016-01-01','end':'2027-11-30'},'calendar.json')
        if schedule(calendar)!=p['schedule']:raise ValueError('Calendar schedule changed; preserve study and review')
        closed=[r['date'] for r in calendar if instant(r['date'],'16:15')<=now]
        last=closed[-1]
        due=missing if missing and window(missing,now)=='ready' else None
        if due and due['decision_date']!=last:raise ValueError('Forecast cutoff drift')
        if not due and (root/'observed'/f'{last}.json').exists():
            status(root,'waiting_for_next_session',last_observed=last,next_decision=missing);return
        if not due and last<p['schedule'][0]['entry_date']:
            status(root,'waiting_for_first_entry',next_decision=missing);return
        assets=required(reference,'https://paper-api.alpaca.markets/v2/assets',{'status':'active','asset_class':'us_equity'},'assets.json')
        fresh=identities(p['universe']+['SPY'],assets);pinned=read(root/'initial/identities.json')
        changed=[s for s in pinned if fresh[s]['id']!=pinned[s]['id'] or fresh[s]['name']!=pinned[s]['name']]
        if changed:raise ValueError('Identity changed; no automatic substitution: '+','.join(changed))
        start='2016-01-01' if due else p['schedule'][0]['entry_date']
        names=p['universe']+['SPY'];payloads=[]
        asof=read(root/'initial/roster-source.json')['captured_at'][:10]
        for j in range(0,len(names),60):
            params={'symbols':','.join(names[j:j+60]),'start':start,'end':last+'T23:59:59Z','timeframe':'1Day',
                    'limit':10000,'sort':'asc','adjustment':'all','asof':asof,'feed':'sip','currency':'USD'}
            tokens=set()
            for n in range(30):
                payload=required(market,'https://data.alpaca.markets/v2/stocks/bars',dict(params),f'bars-{j:03}-{n:02}.json');payloads.append(payload)
                token=payload.get('next_page_token')
                if not token: break
                if token in tokens:raise ValueError('Repeated pagination token')
                tokens.add(token);params['page_token']=token
            else:raise ValueError('Pagination bound exceeded')
        panel=build_panel(payloads,calendar,p['universe'],last,start,read(root/'initial/roster-source.json'))
        save(run/'panel.json',panel,True)
        envelope={'protocol_sha256':sha(root/'protocol.json'),'panel_sha256':sha(run/'panel.json'),
                  'reference_receipt_sha256':sha(run/'reference/receipt.json'),'market_receipt_sha256':sha(run/'market/receipt.json'),
                  'plan':due,'observed_through':last,'created_at':datetime.now(timezone.utc).isoformat()}
        save(run/'envelope.json',envelope,True)
        env={**os.environ,'PYTHONPATH':str(HERE),'OMP_NUM_THREADS':'4','OPENBLAS_NUM_THREADS':'4'}
        subprocess.run([str(HERE/'.venv-prediction-lab/bin/python'),str(Path(__file__).resolve()),'finish','--root',str(root),'--run',str(run)],cwd=HERE,env=env,check=True,timeout=900)
    finally:
        for e in engines:e.dispose()


def finish(root,run):
    p=verify_protocol(root);e=read(run/'envelope.json');panel=read(run/'panel.json')
    for file,key in [('panel.json','panel_sha256'),('reference/receipt.json','reference_receipt_sha256'),('market/receipt.json','market_receipt_sha256')]:
        if sha(run/file)!=e[key]:raise ValueError('Capture hash changed')
    for folder in ['reference','market']:
        for name,r in read(run/folder/'receipt.json')['responses'].items():
            if sha(run/folder/name)!=r['sha256']:raise ValueError('Raw capture changed')
    if e['protocol_sha256']!=sha(root/'protocol.json'):raise ValueError('Capture protocol mismatch')
    due=e['plan'];planmap={r['decision_date']:r for r in p['schedule']}
    if due:
        if due!=planmap.get(due['decision_date']) or window(due,datetime.now(timezone.utc))!='ready':raise ValueError('Decision window closed or plan mismatch')
        from scripts.research.forecast_prediction_improvements import forecast
        previous_path=root/'decisions'/(p['schedule'][due['number']-1]['decision_date']+'.json') if due['number'] else None
        prior=read(previous_path) if previous_path else None
        result=forecast(panel,due['decision_date'],prior['candidate_selected'] if prior else [])
        if window(due,datetime.now(timezone.utc))!='ready':raise ValueError('Model finished after deadline; do not backfill')
        result.update({'plan':due,'protocol_sha256':sha(root/'protocol.json'),'panel_path':str((run/'panel.json').relative_to(root)),
                       'panel_sha256':sha(run/'panel.json'),'previous_sha256':sha(previous_path) if previous_path else None,
                       'created_at':datetime.now(timezone.utc).isoformat()})
        path=root/'decisions'/(due['decision_date']+'.json')
        save(path,result,True)
        save(root/'decision-locks'/path.name,{'sha256':sha(path)},True)
    decisions=decision_files(root)
    # Independently replay the frozen selections using observed adjusted opens only.
    report={'state':'waiting_for_two_observed_opens','scope':p['evidence_scope'],'decision_count':len(decisions),
            'observed_through':e['observed_through'],'protocol_sha256':sha(root/'protocol.json')}
    rows=[];dates=panel['dates'];final=len(dates)-1
    for path in decisions:
        d=read(path);plan=planmap[d['decision_date']]
        if d['plan']!=plan:raise ValueError('Frozen decision plan mismatch')
        previous=root/'decisions'/(p['schedule'][plan['number']-1]['decision_date']+'.json') if plan['number'] else None
        if d.get('previous_sha256') != (sha(previous) if previous else None):raise ValueError('Decision chain mismatch')
        if d['protocol_sha256']!=sha(root/'protocol.json') or sha(root/d['panel_path'])!=d['panel_sha256']:
            raise ValueError('Frozen decision input mismatch')
        if datetime.fromisoformat(d['created_at'])>=datetime.fromisoformat(plan['freeze_deadline']):raise ValueError('Late decision')
        if plan['entry_date'] not in dates or dates.index(plan['entry_date'])>=final:continue
        t=dates.index(plan['entry_date']);end=min(t+21,final)
        rows.append({'origin_index':t-1,'entry_index':t,'exit_index':end,'truncated':end<t+21,
                     'eligible_symbols':d['eligible_symbols'],'baseline_selected':d['baseline_selected'],'candidate_selected':d['candidate_selected']})
    if rows:
        from scripts.research.prediction_wide_portfolios import simulate
        from scripts.research.verify_prediction_wide import replay
        from scripts.research.evaluate_astra_capsules import compare_recursive
        costs={};positions={s:i for i,s in enumerate(p['universe'])}
        for bps in p['parameters']['cost_bps_per_side']:
            variants={}
            for name,key in [('hgb','baseline_selected'),('hgb_buffer','candidate_selected'),('SPY',None)]:
                targets=[]
                for row in rows:
                    weights=[0.]*(len(positions)+1)
                    if key:
                        for s in row[key]:weights[positions[s]]=1/len(row[key])
                    else:weights[-1]=1.
                    targets.append({**row,'target_weights':weights})
                model='SPY' if name=='SPY' else 'frozen_target'
                a=simulate(panel,targets,model,bps/10000);b=replay(panel,targets,model,bps/10000);compare_recursive(a,b)
                # Very short-window annualization is not useful to the user.
                a.pop('cagr',None);variants[name]=a
            costs[str(bps)]=variants
        report.update({'state':'adjusted_price_diagnostic_only','costs':costs,'independent_replay':'passed',
                       'reported_through':dates[rows[-1]['exit_index']],
                       'completed_holding_periods':sum(not r['truncated'] for r in rows),
                       'complete_economic_performance':'unqualified_pending_corporate_action_reconciliation',
                       'valuation_policy':'Observed open marks with hypothetical liquidation costs at report endpoint; no actual fills or interim strategy changes'})
    save(run/'comparison.json',report,True)
    save(root/'observed'/(e['observed_through']+'.json'),{'run':str(run.relative_to(root)),'comparison_sha256':sha(run/'comparison.json')})
    save(root/'comparison-latest.json',report)
    next_plan=next((r for r in p['schedule'] if not (root/'decisions'/(r['decision_date']+'.json')).exists()),None)
    status(root,'forward_observations_recorded',decision_count=len(decisions),latest_report=str((run/'comparison.json').relative_to(root)),next_decision=next_plan,
           study_horizon_observed=e['observed_through']>=p['schedule'][-1]['exit_date'])


def main():
    ap=argparse.ArgumentParser();ap.add_argument('stage',choices=['prepare','tick','finish','verify']);ap.add_argument('--root',type=Path,required=True);ap.add_argument('--run',type=Path)
    a=ap.parse_args();root=a.root.resolve()
    if a.stage=='prepare':prepare(root)
    elif a.stage=='tick':tick(root)
    elif a.stage=='finish':finish(root,a.run.resolve())
    else:verify_protocol(root);print('Frozen forward protocol and source hashes verified')

if __name__=='__main__':main()
