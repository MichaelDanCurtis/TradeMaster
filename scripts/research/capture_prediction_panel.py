"""Freeze an exploratory protocol, then GET adjusted daily bars and calendar only."""
from __future__ import annotations
import argparse, hashlib, json, math
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SYMBOLS = 'AAPL MSFT NVDA JPM BAC GS JNJ MRK UNH PG KO PEP XOM CVX COP CAT HON DE AMZN HD MCD NEE DUK SO APD SHW ECL AMT PLD O VZ T CMCSA'.split()
FIELDS = {'open':'o','high':'h','low':'l','close':'c','volume':'v','vwap':'vw'}

def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def protocol():
    return {
        'version':'prediction-lab-v1', 'declared_at':datetime.now(timezone.utc).isoformat(),
        'symbols':SYMBOLS, 'benchmark':'SPY', 'requested_start':'2015-01-01', 'end':'2026-09-04',
        'evaluation_start':'2023-01-03',
        'coverage_rule':'Use latest first available session across all frozen symbols; require every exchange session thereafter through end. Fail on interior gaps, never fill or drop symbols. Require 252 warmup and at least 24 mature training origins.',
        'data':{'feed':'sip','adjustment':'all','asof':'-','currency':'USD','timeframe':'1Day'},
        'ranking':{'cadence':21,'hold':21,'top_fraction':'1/3 equal weighted; deterministic symbol-order tie break',
            'features':['return5','return21','return63','momentum126minus21','momentum252minus21','vol21','vol63','drawdown63','volume5over63','logdollarvolume21'],
            'feature_scaling':'cross-sectional ranks [-1,1], average ties, constants zero',
            'label':'next-open21-session return minus same-universe mean',
            'training':'origins252,273,...; expanding; only exit_index<=decision_index; initial history before evaluation plus matured subsequent labels',
            'models':{'momentum_12_1':'close[t-21]/close[t-252]-1','ridge':'MSE+1*L2; alpha=n_train; intercept',
                'hgb':{'max_iter':100,'learning_rate':0.03,'max_depth':2,'max_leaf_nodes':4,'min_samples_leaf':50,'l2_regularization':1,'early_stopping':False,'random_state':59137}}},
        'reversal':{'cadence':5,'hold':5,'plain':'negative last5 daily logreturn sum',
            'residual':'OLS intercept/beta to SPY on60 logreturns ending t-5; negative sum of following5 residuals',
            'controls':['momentum12-1 at same5day cadence','equal weight same stocks','SPY buyhold','cash0']},
        'risk':{'origins':'every21 from first session>=2023-01-03; t>=504 and t+22<N','horizons':[5,20],
            'target':'future mean squared daily close-to-close logreturns; variance proxy',
            'models':['trailing20 mean squared logreturn','EWMA lambda0.94 trailing504 init first20','GARCH11 Gaussian zero mean trailing504 percentage logreturns; maxiter1000'],
            'primary':'matched-case QLIKE; paired time-block uncertainty; no strategy overlay'},
        'execution':'Signal at close t, entry open t+1, exit open t+hold+1. Fractional adjusted-price proxy units. Long only, no leverage. Costs charged on buys and sells at rebalances and final liquidation using drifted holdings.',
        'cost_bps_per_side':[11,22], 'cash_interest':0,
        'controls':['equal weight same frozen33 stocks on matched rebalance dates','SPY buyhold with entry/final fees','cash0'],
        'metrics':['net return','CAGR','maximum drawdown from daily open marks','annual slices','turnover','concentration','rank correlation','paired block bootstrap excess-return uncertainty'],
        'bootstrap':{'seed':59137,'draws':5000,'monthly_block_origins':3,'weekly_block_origins':12},
        'limitations':['Hand-picked current survivors, not a point-in-time investable universe; survivorship/selection bias.',
            'Current revised adjusted bars, not vintage prices. Adjusted opens are total-return proxies, not executable historical quotes.',
            'Exploratory retrospective evaluation; dates may overlap prior research; not an untouched holdout.',
            'Cost assumptions are hypothetical and exclude taxes, market impact beyond fixed slippage and financing.',
            'No parameter reselection after viewing scores; report all fixed candidates and failures.',
            'No orders, no schedule changes, no admission into the separately frozen paper-trial evidence.'],
        'sources':['https://docs.alpaca.markets/us/reference/stockbars','https://dachxiu.chicagobooth.edu/download/ML_BKP.pdf',
            'https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_developed_mom.html',
            'https://academicweb.nd.edu/~zda/Reversal.pdf','https://arch.readthedocs.io/en/latest/univariate/forecasting.html']}

def build_panel(pages, calendar, intent):
    names=intent['symbols']+[intent['benchmark']]
    records={s:{} for s in names}
    for payload in pages:
        for symbol,bars in payload['bars'].items():
            if symbol not in records: raise ValueError('Unexpected symbol')
            for bar in bars:
                day=datetime.fromisoformat(bar['t'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                if day in records[symbol]: raise ValueError(f'Duplicate {symbol} {day}')
                values={field:float(bar[key]) for field,key in FIELDS.items()}
                if not all(math.isfinite(v) and (v>=0 if k=='volume' else v>0) for k,v in values.items()): raise ValueError(f'Invalid value {symbol} {day}')
                if values['low']>min(values['open'],values['close'])+1e-6 or values['high']<max(values['open'],values['close'])-1e-6: raise ValueError(f'Invalid OHLC {symbol} {day}')
                records[symbol][day]=values
    if any(not rows for rows in records.values()): raise ValueError('Missing symbol history')
    start=max(min(rows) for rows in records.values())
    dates=sorted(row['date'] for row in calendar if start<=row['date']<=intent['end'])
    if len(set(dates))!=len(dates): raise ValueError('Duplicate calendar')
    if not dates or dates[-1]!=intent['end']: raise ValueError('Incomplete calendar')
    missing={s:[d for d in dates if d not in records[s]] for s in names}
    if any(missing.values()): raise ValueError('Missing calendar bars: '+json.dumps({s:d[:8] for s,d in missing.items() if d}))
    extras={s:sorted(set(rows)-set(dates)) for s,rows in records.items()}
    return {'dates':dates,'symbols':intent['symbols'],'benchmark':intent['benchmark'],
        'series':{s:{field:[records[s][d][field] for d in dates] for field in FIELDS} for s in names},
        'coverage':{'first_dates':{s:min(rows) for s,rows in records.items()},'last_dates':{s:max(rows) for s,rows in records.items()},
            'excluded_outside_common_calendar':{s:len(d) for s,d in extras.items()},'missing_count':0},
        'limitations':intent['limitations']}

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--output',type=Path,required=True);args=ap.parse_args()
    root=args.output;root.mkdir(parents=True,exist_ok=False);(root/'raw').mkdir()
    intent=protocol();write(root/'protocol.json',intent)
    # Resolve only the existing read interfaces; never instantiate an execution workflow.
    from dotenv import load_dotenv
    from tradingagents.ui.db import create_session_factory
    from tradingagents.ui.repository import UiRepository
    from tradingagents.ui.api import _resolve_market_data_provider
    from tradingagents.research.deployment_cycle_child import resolve_configured_broker
    load_dotenv('.env');engine,sessions=create_session_factory('sqlite:///.tradingagents-ui.db')
    repo=UiRepository(sessions);data,_=_resolve_market_data_provider('alpaca-market-data',{},repo,None)
    broker=resolve_configured_broker(sessions)
    receipts=[]
    def get(source,url,params,name):
        response=source._http_client.get(url,headers=source._headers(),params=params,timeout=30,allow_redirects=False)
        if response.status_code!=200: raise RuntimeError(f'Capture HTTP {response.status_code}; response not logged')
        path=root/'raw'/name;path.write_bytes(response.content)
        receipts.append({'file':str(path.relative_to(root)),'sha256':digest(path),'url':url,'params':dict(params),'captured_at':datetime.now(timezone.utc).isoformat(),'bytes':len(response.content)})
        write(root/'capture-receipt.json',{'protocol_sha256':digest(root/'protocol.json'),'responses':receipts,'complete':False})
        return response.json()
    calendar=get(broker,'https://paper-api.alpaca.markets/v2/calendar',{'start':intent['requested_start'],'end':intent['end']},'calendar.json')
    params={'symbols':','.join(SYMBOLS+['SPY']),'start':intent['requested_start'],'end':'2026-09-04T23:59:59Z','limit':10000,'sort':'asc',**intent['data']}
    pages=[];tokens=set();count=0
    for page in range(20):
        payload=get(data,'https://data.alpaca.markets/v2/stocks/bars',params,f'bars-{page:02}.json')
        pages.append(payload);count+=sum(len(v) for v in payload['bars'].values())
        print(f'Captured page {page+1}: {count} bars',flush=True)
        if count>150000: raise RuntimeError('Row limit exceeded')
        token=payload.get('next_page_token')
        if not token: break
        if token in tokens: raise RuntimeError('Repeated pagination token')
        tokens.add(token);params['page_token']=token
    else: raise RuntimeError('Page limit exceeded')
    panel=build_panel(pages,calendar,intent);write(root/'panel.json',panel)
    write(root/'capture-receipt.json',{'protocol_sha256':digest(root/'protocol.json'),'panel_sha256':digest(root/'panel.json'),'responses':receipts,'complete':True,'bar_count':count,'sessions':len(panel['dates'])})
    engine.dispose()
    print(json.dumps({'sessions':len(panel['dates']),'start':panel['dates'][0],'end':panel['dates'][-1],'stocks':len(SYMBOLS),'panel_sha256':digest(root/'panel.json')}))
if __name__=='__main__':main()
