"""Read-only trial research capture. Never approves, funds, or submits orders."""
import json
import signal
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote
from dotenv import load_dotenv
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.api import _resolve_market_data_provider
from tradingagents.research.deployment_cycle_child import resolve_configured_broker
from tradingagents.research.data.alpaca_capture import DailyBarRequest, CaptureLimits, capture_daily_bars, read_capture, capture_summary
from tradingagents.research.data.alpaca_reference import ReferenceRequest, capture_reference, read_reference_capture
from tradingagents.research.data.store import ArtifactStore


def main():
    load_dotenv('.env')
    root=Path('.research-artifacts/paper-trial');root.mkdir(parents=True,exist_ok=True)
    index=root/'research-capture-index.json'
    if index.exists():
        print('Existing capture retained:',index);return
    signal.signal(signal.SIGALRM,signal.SIG_DFL);signal.alarm(240)
    engine,sessions=create_session_factory('sqlite:///.tradingagents-ui.db')
    repo=UiRepository(sessions);broker=resolve_configured_broker(sessions)
    data,config=_resolve_market_data_provider('alpaca-market-data',{},repo,None)
    store=ArtifactStore(root/'objects')
    # Save the evaluation contract before fetching or inspecting price outcomes.
    criteria={'version':'paper-trial-research-review-v1','declared_at':datetime.now(timezone.utc).isoformat(),
        'strategy_id':'strategy_a22875160d71409da2d734fe3ede16d8',
        'design_id':'design_994c331466f144dcb1bec945f31a0991',
        'symbols':['AAPL','MSFT','NVDA','SPY'],'warmup':['2022-01-01','2022-12-31'],
        'development':['2023-01-01','2023-12-31'],'validation':['2024-01-01','2024-12-31'],
        'historical_holdout':['2025-01-01','2026-09-04'],
        'controls':['cash with zero interest assumption','equal-weight same four instruments, 20% cash, weekly rebalance, same fees and execution convention'],
        'execution_convention':'next regular session open; no same-close trades; missing usable inputs mean no signal',
        'cost_assumptions':{'commission_bps_per_side':1,'slippage_bps_per_side':10,'stress_multiplier':2},
        'criteria':['net excess return above matched equal-weight control in validation and historical holdout',
            'repeat comparison at twice assumed costs without parameter reselection',
            'report realized maximum drawdown, turnover, concentration and all failed attempts',
            'drawdown beyond proposed 5% intervention threshold requires review; threshold is not a loss guarantee',
            'historical evidence cannot qualify the strategy without verified data provenance and temporal availability',
            'five prospective sessions provide operational observations, not statistically established profitability'],
        'limitations':['Current watchlist was selected after historical outcomes; selection bias remains',
            'Astra may know historical outcomes; historical holdout is not independent prospective evidence',
            'No parameters may be tuned against validation/holdout results and silently reused',
            'Data access success does not establish redistribution rights, consolidated coverage, or point-in-time completeness']}
    record={'criteria_hash':store.put_json(criteria),'captures':{},'assets':{},'status':'capturing'}
    index.write_text(json.dumps(record,indent=2))
    limits=CaptureLimits(max_pages=10,max_rows=20000,elapsed_seconds=60)
    def save():index.write_text(json.dumps(record,indent=2))
    bars=capture_daily_bars(DailyBarRequest(symbols=criteria['symbols'],start='2022-01-01T00:00:00Z',end='2026-09-05T00:00:00Z',feed='iex'),store,
        secret_store=data._secret_store,secret_ref=data._secret_ref,limits=limits)
    record['captures']['bars']={'hash':bars,**capture_summary(read_capture(store,bars))};save()
    for kind in ['calendar','corporate_actions']:
        r=ReferenceRequest(kind=kind,start=date(2022,1,1),end=date(2026,9,4),symbols=criteria['symbols'] if kind=='corporate_actions' else [])
        source=broker if kind=='calendar' else data
        digest=capture_reference(r,store,secret_store=source._secret_store,secret_ref=source._secret_ref,limits=limits)
        receipt=read_reference_capture(store,digest)
        record['captures'][kind]={'hash':digest,'status':receipt.status,'failure_code':receipt.failure_code,'unique_rows':receipt.unique_rows};save()
    for symbol in criteria['symbols']:
        asset=broker._read('assets/'+quote(symbol,safe=''))
        if asset.get('symbol')!=symbol or asset.get('class')!='us_equity' or asset.get('status')!='active' or asset.get('tradable') is not True:
            raise ValueError('Unexpected asset identity or trading eligibility')
        digest=store.put_json({'observed_at':datetime.now(timezone.utc).isoformat(),'source':'alpaca-v2-assets','asset':asset})
        record['assets'][symbol]={'hash':digest,'asset_id':asset['id'],'exchange':asset['exchange'],'scope':'current identity only; historical mapping not certified'};save()
    record['status']='captured_for_review';record['snapshot_admitted']=False;save()
    print(json.dumps(record,indent=2))

if __name__=='__main__':main()
