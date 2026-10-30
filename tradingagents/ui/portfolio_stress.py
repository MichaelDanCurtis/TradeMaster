"""Explicit price-shock scenarios over a preserved paper-account observation."""
from decimal import Decimal
from pathlib import Path
from typing import Annotated
import os
import threading
from fastapi import APIRouter,HTTPException
from fastapi.responses import Response
from pydantic import Field,StringConstraints
from tradingagents.research.contracts import Contract,canonical_json,content_hash
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.execution_contracts import PaperAccountSnapshot
from tradingagents.ui.research_desk import Symbol,local_portfolio_context

Shock=Annotated[Decimal,Field(ge=-100,le=500,allow_inf_nan=False,decimal_places=4)]
class StressRequest(Contract):
    snapshot_id: str
    name: Annotated[str,StringConstraints(strip_whitespace=True,min_length=1,max_length=100)]
    default_shock_pct: Shock = Decimal(-20)
    overrides: Annotated[dict[Symbol,Shock],Field(max_length=200)] = {}
    request_key: Annotated[str,StringConstraints(pattern=r'^[a-zA-Z0-9_-]{16,100}$')]


def check_snapshot(snapshot):
    if not snapshot.complete or snapshot.evidence_kind!='broker_paper' or snapshot.equity_usd<=0:
        raise ValueError('A complete positive-equity paper account is required')
    if any(p.market_value_usd<0 for p in snapshot.positions):
        raise ValueError('This scenario requires long holdings; short-position shocks are not implemented')
    residual=snapshot.equity_usd-snapshot.cash_usd-sum((p.market_value_usd for p in snapshot.positions),Decimal(0))
    if abs(residual)>Decimal('.05'):
        raise ValueError('Cash and direct positions do not reconcile to equity within five cents')
    return residual


def stress_result(snapshot,request):
    residual=check_snapshot(snapshot)
    holdings={p.symbol:p for p in snapshot.positions}
    if set(request.overrides)-set(holdings):
        raise ValueError('A shock override refers to a symbol absent from this snapshot')
    rows=[];change=Decimal(0)
    for symbol,p in holdings.items():
        shock=request.overrides.get(symbol,request.default_shock_pct)
        delta=p.market_value_usd*shock/100;change+=delta
        rows.append({'symbol':symbol,'quantity':str(p.quantity),'shock_pct':str(shock),'value_before_usd':str(p.market_value_usd),'value_after_usd':str(p.market_value_usd+delta),'change_usd':str(delta),'weight_before_pct':str(p.market_value_usd/snapshot.equity_usd*100)})
    after=snapshot.equity_usd+change
    for row in rows:row['weight_after_pct']=str(Decimal(row['value_after_usd'])/after*100) if after>0 else None
    return {'observed_at':snapshot.observed_at.isoformat(),'equity_before_usd':str(snapshot.equity_usd),'equity_after_usd':str(after),
        'change_usd':str(change),'change_pct':str(change/snapshot.equity_usd*100),'cash_usd':str(snapshot.cash_usd),
        'cash_weight_after_pct':str(snapshot.cash_usd/after*100) if after>0 else None,'reconciliation_residual_usd':str(residual),
        'holdings':sorted(rows,key=lambda x:Decimal(x['change_usd'])),
        'limitations':['User-selected simultaneous price changes, not forecasts, probabilities, VaR or observed drawdown.',
            'An override replaces the common shock for that symbol; it is not added to it. Cash and quantities stay fixed.',
            'No order fills, rebalancing, fees, taxes, dividends, margin liquidation or ETF constituent look-through are simulated.',
            'Open orders and local commitments are preserved separately; they are not assumed to fill.',
            'Negative or zero stressed equity makes percentage concentration undefined. The starting residual of up to five cents remains unchanged.']}


def create_stress_router(desk,broker_resolver,store=None):
    store=store or ArtifactStore(Path(os.environ.get('TRADEMASTER_RESEARCH_ARTIFACTS','.research-artifacts'))/'stress'/'objects')
    router=APIRouter(prefix='/api/discover/stress');lock=threading.Lock()
    @router.get('')
    def history():return {'snapshots':desk.rows('stress_snapshot'),'scenarios':desk.rows('stress_scenario')}
    @router.post('/snapshots')
    def capture():
        try:
            snapshot=broker_resolver().paper_snapshot();check_snapshot(snapshot)
            known=sum((o.remaining_quantity*o.maximum_price_usd for o in snapshot.open_orders if o.side=='buy' and o.maximum_price_usd is not None),Decimal(0))
            context=local_portfolio_context(desk.sessions,snapshot,None,{'cash_after_known_commitments_usd':str(snapshot.cash_usd-known),
                'cash_coverage':'unknown' if any(o.side=='buy' and o.maximum_price_usd is None for o in snapshot.open_orders) else 'covered_before_fees','limitations':[]})
            document={'snapshot':snapshot.model_dump(mode='json'),'local_commitments':context}
            digest=store.put_json(document)
        except ValueError as e:
            safe = {'A complete positive-equity paper account is required',
                'This scenario requires long holdings; short-position shocks are not implemented',
                'Cash and direct positions do not reconcile to equity within five cents'}
            raise HTTPException(409,str(e) if str(e) in safe else 'Account capture or commitment validation failed. No scenario was saved.') from None
        except Exception:raise HTTPException(409,'Could not capture a complete paper account. No scenario was saved.') from None
        return desk.save('stress_snapshot','',{'snapshot_hash':digest,'observed_at':snapshot.observed_at.isoformat(),
            'equity_usd':str(snapshot.equity_usd),'cash_usd':str(snapshot.cash_usd),'account_suffix':snapshot.account_id[-4:],
            'holdings':[p.model_dump(mode='json') for p in snapshot.positions],'open_orders':[o.model_dump(mode='json') for o in snapshot.open_orders],
            'local_commitments':context})
    def source(identifier):
        row=desk.get(identifier,'stress_snapshot')
        document=store.json(row['payload']['snapshot_hash'])
        return row,document,PaperAccountSnapshot.model_validate(document['snapshot'])
    @router.post('/scenarios')
    def run(request:StressRequest):
        with lock:
            digest=content_hash(request)
            for previous in desk.rows('stress_scenario',limit=10000):
                if previous['payload']['request']['request_key']==request.request_key:
                    if previous['payload']['request_hash']!=digest:raise HTTPException(409,'Request key already used with different scenario inputs')
                    return previous
            try:
                row,document,snapshot=source(request.snapshot_id)
                result=stress_result(snapshot,request)
                receipt={'request':request.model_dump(mode='json'),'request_hash':digest,'snapshot_hash':row['payload']['snapshot_hash'],
                    'calculation_version':'explicit-price-shocks-v1','calculation_code_hash':content_hash({'source':Path(__file__).read_text()}),'result':result,
                    'local_commitments':document['local_commitments']}
                receipt_hash=store.put_json(receipt)
            except (ValueError,OSError):raise HTTPException(409,'Snapshot integrity or scenario validation failed; check that overrides refer to held symbols.') from None
            return desk.save('stress_scenario','',{**receipt,'receipt_hash':receipt_hash})
    @router.get('/scenarios/{identifier}/evidence.json')
    def export(identifier:str):
        row=desk.get(identifier,'stress_scenario')
        try:
            receipt=store.json(row['payload']['receipt_hash']);document=store.json(receipt['snapshot_hash'])
            if content_hash({k:v for k,v in row['payload'].items() if k!='receipt_hash'})!=row['payload']['receipt_hash']:
                raise ValueError('Scenario metadata changed')
        except (ValueError,OSError):raise HTTPException(409,'Preserved scenario failed integrity verification') from None
        return Response(canonical_json({'scenario_id':identifier,'receipt_hash':row['payload']['receipt_hash'],'receipt':receipt,'account_evidence':document}),media_type='application/json',headers={'Content-Disposition':'attachment; filename="portfolio-stress-evidence.json"'})
    return router
