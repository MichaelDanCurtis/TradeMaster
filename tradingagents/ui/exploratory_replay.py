"""Fixed development-only experiment. Reconstructed history cannot be promoted."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo
import json
from tradingagents.research.contracts import StrategySpec, CostScenario, content_hash
from tradingagents.research.models import StrategyDesignRecord
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.data.alpaca_capture import read_capture
from tradingagents.research.data.alpaca_reference import read_reference_capture, _reference_records, calendar_session
from tradingagents.research.data.contracts import DatasetBundle, MarketBar, SecurityMapping, CorporateAction
from tradingagents.research.engines.base import ReplayRequest
from tradingagents.research.engines.replay import LocalReplayEngine

DESIGN='design_994c331466f144dcb1bec945f31a0991'
ASSUMPTIONS=[
    'Retrospective development-only experiment: 2022 warmup and 2023 evaluation. No validation or holdout performance calculated.',
    'Original captures were received in September 2026. This reconstruction assumes daily bars available one second after their historical session close; historical revisions are unverified.',
    'Current AAPL/MSFT/NVDA/SPY mappings are assumed valid throughout 2022-2023; survivorship and current-watchlist selection bias remain.',
    'Captured ordinary cash dividends are assumed USD with payment at the end of the payable date in New York. Dividend knowledge is assumed at ex-date open; announcement history is unverified.',
    'NUAN cash merger is retained in the source artifact but excluded from MSFT share accounting because MSFT is the acquirer. Any other unsupported in-window action aborts the run.',
    'Next-session daily open is a simulation proxy, not an auction or broker fill. Cash yield is zero; initial simulated capital is $100,000.',
    'Frozen input copy of the existing Astra design, with no parameter search. Base cost 1bp commission plus 10bps slippage per side; stress doubles both.',
    'Results are exploratory, not valid prospective performance or a deployment eligibility receipt. Existing trial criteria and approvals are unchanged.'
]

def run_development(sessions, root=Path('.research-artifacts/paper-trial')):
    store=ArtifactStore(root/'objects');out=ArtifactStore(Path('.research-artifacts/development/objects'))
    index=json.loads((root/'research-capture-index.json').read_text());sip=json.loads((root/'sip-capture-review.json').read_text())
    with sessions() as session:
        design=session.get(StrategyDesignRecord,DESIGN)
        if not design or design.state!='completed' or not design.receipt: raise ValueError('Reviewed design unavailable')
        spec=StrategySpec.model_validate(design.receipt['proposal']['spec'])
    ids={i.symbol:i.instrument_id for i in spec.universe}
    if set(ids)!={'AAPL','MSFT','NVDA','SPY'} or spec.rules.kind!='diversified_trend':raise ValueError('Development universe changed')
    end=date(2023,12,31);zone=ZoneInfo('America/New_York')
    cal=read_reference_capture(store,index['captures']['calendar']['hash'])
    if cal.status!='complete':raise ValueError('Incomplete calendar')
    records,_=_reference_records(store,cal)
    calendar=[calendar_session(r) for r in records.values() if date(2022,1,1)<=date.fromisoformat(r['date'])<=end]
    by_day={s.date:s for s in calendar};bars=[]
    receipt=read_capture(store,sip['hash'])
    if receipt.status!='complete' or receipt.request.feed!='sip' or receipt.request.params()['adjustment']!='raw':raise ValueError('Raw SIP capture required')
    for page in receipt.pages:
        for symbol,rows in store.json(page.response_artifact)['bars'].items():
            for row in rows:
                day=datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(zone).date()
                if day not in by_day:continue
                bars.append(MarketBar(instrument_id=ids[symbol],session=day,open=row['o'],high=row['h'],low=row['l'],close=row['c'],volume=row['v'],available_at=by_day[day].closes_at+timedelta(seconds=1)))
    actions_capture=read_reference_capture(store,index['captures']['corporate_actions']['hash'])
    if actions_capture.status!='complete':raise ValueError('Incomplete corporate action capture')
    actions=[];excluded=[]
    raw_actions,_=_reference_records(store,actions_capture)
    for identifier,item in raw_actions.items():
        row=item['record'];category=item['category']
        if category=='cash_mergers' and row.get('acquiree_symbol')=='NUAN' and row.get('acquirer_symbol')=='MSFT':
            excluded.append({'id':identifier,'reason':'NUAN merger does not adjust acquirer MSFT shares'});continue
        effective=row.get('ex_date') or row.get('effective_date')
        if effective and not date(2022,1,1)<=date.fromisoformat(effective)<=end:
            excluded.append({'id':identifier,'reason':'Ex/effective date outside warmup and development window; no opening positions'})
            continue
        if category!='cash_dividends':raise ValueError('Unsupported development corporate action')
        day=date.fromisoformat(row['ex_date'])
        if day not in by_day or row.get('symbol') not in ids:raise ValueError('Dividend outside mapped calendar')
        if row.get('foreign') or row.get('special'):raise ValueError('Nonordinary dividend needs review')
        actions.append(CorporateAction(action_id=identifier,instrument_id=ids[row['symbol']],kind='dividend',effective_session=day,
            available_at=by_day[day].opens_at,cash_per_share_usd=row['rate'],payable_at=datetime.combine(date.fromisoformat(row['payable_date']),time(23,59,59),zone)))
    first=min(by_day)
    dataset=DatasetBundle(timezone='America/New_York',sessions=calendar,bars=bars,actions=actions,
        mappings=[SecurityMapping(instrument_id=i.instrument_id,symbol=i.symbol,valid_from=first,known_at=datetime(2022,1,1,tzinfo=timezone.utc)) for i in spec.universe])
    for identifier in ids.values():
        if {b.session for b in dataset.bars if b.instrument_id==identifier}!=set(by_day):raise ValueError('Incomplete development bar coverage')
    dataset_hash=out.put_json(dataset.model_dump(mode='json'))
    engine=LocalReplayEngine()
    manifest={'schema':'retrospective_development_v1','design_id':DESIGN,'spec':spec.model_dump(mode='json'),'dataset_hash':dataset_hash,
              'source_capture_hashes':{'bars':sip['hash'],'calendar':index['captures']['calendar']['hash'],'actions':index['captures']['corporate_actions']['hash']},
              'adapter_sha256':__import__('hashlib').sha256(Path(__file__).read_bytes()).hexdigest(),'assumptions':ASSUMPTIONS,'excluded_actions':excluded,'engine_build':engine.build,'promotion_eligible':False}
    manifest_hash=out.put_json(manifest)
    cache=Path('.research-artifacts/development')/(manifest_hash+'.json')
    if cache.exists():
        digest=json.loads(cache.read_text())['result_hash'];return out.json(digest)
    results=[]
    for cost,mult in [('base',1),('double_cost',2)]:
        for control in ['strategy','fixed_basket','cash']:
            request=ReplayRequest(dataset=dataset,spec=spec,start=date(2023,1,1),end=end,initial_capital_usd=Decimal(100000),cash_annual_yield_fraction=0,
                scenario=CostScenario(name=cost,slippage_bps=10*mult,commission_usd=0,commission_bps=mult),control=control)
            result=engine.run(request);payload=result.model_dump(mode='json');digest=out.put_json(payload)
            if not result.equity:raise ValueError('Engine produced no valuations')
            high=Decimal(100000);drawdown=Decimal(0)
            for point in result.equity:
                high=max(high,point.equity_usd);drawdown=max(drawdown,(high-point.equity_usd)/high)
            results.append({'cost':cost,'control':control,'net_return_pct':str((result.equity[-1].equity_usd/Decimal(100000)-1)*100),
                'max_drawdown_pct':str(drawdown*100),'fills':len(result.fills),'risk_pauses':sum(e.kind=='risk_pause' for e in result.events),
                'result_hash':digest,'request_hash':out.put_json(request.model_dump(mode='json'))})
    report={'state':'completed','promotion_eligible':False,'manifest_hash':manifest_hash,'dataset_hash':dataset_hash,
            'assumptions':ASSUMPTIONS,'results':results,'period':'2023 development only','created_at':datetime.now(timezone.utc).isoformat()}
    digest=out.put_json(report);cache.parent.mkdir(parents=True,exist_ok=True);cache.write_text(json.dumps({'result_hash':digest}))
    return report
