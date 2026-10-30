"""Persistent research desk; reads and simulations have no execution authority."""
from __future__ import annotations

from tradingagents.ui.lifecycle import on_lifecycle
import asyncio
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field as PF, StringConstraints
from sqlalchemy import Column, JSON
from sqlmodel import SQLModel, Field, select
from tradingagents.ui.models import now_utc, new_id
from tradingagents.ui.company_evidence import CompanySources, screen

Symbol = Annotated[str, StringConstraints(pattern=r'^[A-Z][A-Z0-9.\-]{0,11}$')]

class DeskRecord(SQLModel, table=True):
    __tablename__ = 'ui_research_desk'
    id: str = Field(default_factory=lambda:new_id('desk'), primary_key=True)
    kind: str = Field(index=True)
    symbol: str = Field(default='', index=True)
    created_at: str = Field(default_factory=lambda:now_utc().isoformat(), index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))

class ScreenRequest(BaseModel):
    symbols: list[Symbol] = PF(min_length=1, max_length=12)
    min_growth: float = PF(default=10, ge=-100, le=1000, allow_inf_nan=False)
    min_margin: float = PF(default=0, ge=-1000, le=100, allow_inf_nan=False)
    require_fcf: bool = True

class ThesisRequest(BaseModel):
    snapshot_id: str
    thesis: str = PF(min_length=10, max_length=2000)
    invalidation: str = PF(min_length=10, max_length=2000)
    min_growth: float = PF(default=0, ge=-100, le=1000, allow_inf_nan=False)
    min_margin: float = PF(default=0, ge=-1000, le=100, allow_inf_nan=False)

class AllocationRequest(BaseModel):
    symbol: Symbol
    amount_usd: Decimal = PF(gt=0, le=10000000, allow_inf_nan=False, decimal_places=2)

class Desk:
    def __init__(self, sessions, sources=None):
        self.sessions, self.sources = sessions, sources or CompanySources()
        self.worker = {'state':'stopped', 'checked_at':None, 'error':None}
        import threading
        self.review_lock = threading.Lock()

    def save(self, kind, symbol, payload):
        with self.sessions() as session:
            row = DeskRecord(kind=kind, symbol=symbol, payload=payload)
            session.add(row); session.commit()
            return row.model_dump()

    def rows(self, kind, symbol=None, limit=50):
        with self.sessions() as session:
            query = select(DeskRecord).where(DeskRecord.kind==kind)
            if symbol: query=query.where(DeskRecord.symbol==symbol)
            return [r.model_dump() for r in session.exec(query.order_by(DeskRecord.created_at.desc()).limit(limit)).all()]

    def get(self, identifier, kind):
        with self.sessions() as session:
            row = session.get(DeskRecord, identifier)
            if row is None or row.kind != kind: raise HTTPException(404, 'Saved research record not found')
            return row.model_dump()

    def collect(self, symbol):
        return self.save('company', symbol, self.sources.collect(symbol))

    def review(self, monitor):
        fresh = self.collect(monitor['symbol'])
        baseline = self.get(monitor['payload']['snapshot_id'], 'company')
        previous = next((r for r in self.rows('review',monitor['symbol']) if r['payload']['monitor_id']==monitor['id']), None)
        prior = self.get(previous['payload']['snapshot_id'], 'company') if previous else baseline
        changes = []
        for key in ['revenue_growth','net_margin','pe','market_cap']:
            before, after = prior['payload']['metrics'].get(key), fresh['payload']['metrics'].get(key)
            if before != after: changes.append({'metric':key,'before':before,'after':after})
        for key in set(prior['payload']['financials']) | set(fresh['payload']['financials']):
            before_fact=prior['payload']['financials'].get(key,{})
            after_fact=fresh['payload']['financials'].get(key,{})
            if (before_fact.get('value'),before_fact.get('end')) != (after_fact.get('value'),after_fact.get('end')):
                changes.append({'metric':'annual_'+key,'before':before_fact.get('value'),'after':after_fact.get('value')})
        old = {r['accession'] for r in prior['payload']['filings']}
        new_filings = [r for r in fresh['payload']['filings'] if r['accession'] not in old]
        checks = screen(fresh['payload'], monitor['payload']['min_growth'], monitor['payload']['min_margin'])
        status = 'threshold_breached' if checks['state']=='fail' else 'insufficient_evidence' if checks['state']=='unknown' else 'needs_review' if changes or new_filings else 'no_detected_change'
        return self.save('review',monitor['symbol'], {'monitor_id':monitor['id'], 'snapshot_id':fresh['id'], 'previous_snapshot_id':prior['id'],
            'baseline_snapshot_id':baseline['id'], 'state':status, 'changes':changes, 'new_filings':new_filings, 'checks':checks,
            'interpretation':'Numeric checks only. Free-text invalidation conditions require human review; no AI or trading action was taken.'})

    def due(self):
        if not self.review_lock.acquire(blocking=False): return
        try:
            self.worker.update(state='running', checked_at=now_utc().isoformat(), error=None)
            from datetime import datetime
            reviews = self.rows('review',limit=1000)
            for monitor in self.rows('monitor',limit=100):
                if not monitor['payload'].get('active'): continue
                previous = next((r for r in reviews if r['payload']['monitor_id']==monitor['id']),None)
                if previous and now_utc()-datetime.fromisoformat(previous['created_at']) < timedelta(hours=24): continue
                self.review(monitor)
                break  # One bounded company refresh per worker tick.
        except Exception:
            self.worker['error']='Research review failed; preserved prior results remain available.'
        finally: self.review_lock.release()

def portfolio_impact(snapshot, request):
    if not snapshot.complete or snapshot.evidence_kind != 'broker_paper' or snapshot.equity_usd <= 0:
        raise ValueError('A complete, positive-equity broker paper snapshot is required')
    equity=snapshot.equity_usd;amount=request.amount_usd
    known=sum((o.remaining_quantity*o.maximum_price_usd for o in snapshot.open_orders if o.side=='buy' and o.maximum_price_usd is not None),Decimal(0))
    unbounded=any(o.side=='buy' and o.maximum_price_usd is None for o in snapshot.open_orders)
    holdings={p.symbol:p.market_value_usd for p in snapshot.positions}
    before=holdings.get(request.symbol,Decimal(0));holdings[request.symbol]=before+amount
    return {'observed_at':snapshot.observed_at.isoformat(),'equity_usd':str(equity),'cash_before_usd':str(snapshot.cash_usd),
        'cash_after_usd':str(snapshot.cash_usd-amount),'known_open_buy_commitments_usd':str(known),
        'cash_after_known_commitments_usd':str(snapshot.cash_usd-amount-known),
        'cash_coverage':'unknown' if unbounded else 'insufficient' if amount+known>snapshot.cash_usd else 'covered_before_fees',
        'symbol':request.symbol,'amount_usd':str(amount),'weight_before_pct':str(before/equity*100),
        'weight_after_pct':str((before+amount)/equity*100), 'trading_blocked':snapshot.trading_blocked,
        'holdings':[{'symbol':s,'value_after_usd':str(v),'weight_after_pct':str(v/equity*100)} for s,v in sorted(holdings.items(),key=lambda item:-item[1])],
        'open_orders':[o.model_dump(mode='json') for o in snapshot.open_orders],
        'limitations':['Hypothetical cash purchase at unchanged marks, before fees. No order is created.',
            'Cash coverage is not execution approval. Scheduled local orders are not included in broker open orders.',
            'ETF constituents, historical correlations, taxes, and competing deployment reservations are not inferred.']}

def local_portfolio_context(sessions,snapshot,request,result):
    from tradingagents.research.execution_repository import account_key
    from tradingagents.research.execution_models import PaperReservationRecord, PaperExecutionAttemptRecord, ExactPaperOrderRecord
    from tradingagents.research.deployment_models import StrategyDeploymentRecord, DeploymentTermsRecord
    from tradingagents.scheduling.models import ExecutionSchedule,ScheduledLeg
    key=account_key(snapshot);remote={o.client_order_id for o in snapshot.open_orders};pending=[];scheduled=[];budgets=[]
    with sessions() as session:
        reserved_order_ids=set()
        for r in session.exec(select(PaperReservationRecord).where(PaperReservationRecord.account_key==key,PaperReservationRecord.active==True)):
            attempt=session.get(PaperExecutionAttemptRecord,r.attempt_id)
            if not attempt:raise ValueError('Missing reservation receipt')
            reserved_order_ids.add(attempt.order_id)
            if r.side=='buy':
                amount=(Decimal(0) if attempt.client_order_id in remote else Decimal(r.quantity)*Decimal(r.price_usd))+Decimal(r.fee_usd)
                pending.append({'symbol':r.symbol,'amount_usd':str(amount),'state':attempt.state})
        for schedule in session.exec(select(ExecutionSchedule).where(ExecutionSchedule.account_key==key,ExecutionSchedule.approved_at.is_not(None))):
            if schedule.state not in {'approved','active','running','scheduled'}:continue
            for leg in session.exec(select(ScheduledLeg).where(ScheduledLeg.schedule_id==schedule.schedule_id)):
                order=session.get(ExactPaperOrderRecord,leg.order_id)
                if not order or order.order_id in reserved_order_ids or order.intent_id in remote or order.state in {'filled','canceled','expired','rejected'}:continue
                terms=order.order
                if terms['side']=='buy':scheduled.append({'symbol':terms['symbol'],'schedule_id':schedule.schedule_id,
                    'amount_usd':str(Decimal(str(terms['quantity']))*Decimal(str(terms['limit_price_usd']))+Decimal(str(terms.get('fee_reserve_usd',0))))})
        for deployment in session.exec(select(StrategyDeploymentRecord).where(StrategyDeploymentRecord.account_key==key,StrategyDeploymentRecord.active_terms_id.is_not(None))):
            if deployment.state=='retired':continue
            terms=session.get(DeploymentTermsRecord,deployment.active_terms_id)
            if not terms:raise ValueError('Missing deployment allocation terms')
            budgets.append({'name':deployment.name,'state':deployment.state,'capital_usd':terms.payload['capital_usd']})
    extra=sum((Decimal(r['amount_usd']) for r in pending+scheduled),Decimal(0))
    cash=Decimal(result['cash_after_known_commitments_usd'])-extra
    limitations=[r for r in result['limitations'] if not r.startswith('Cash coverage') and not r.startswith('ETF constituents')]
    limitations += ['Local reservations are deduplicated against broker orders. Approved, undispatched schedule buys are included as planned commitments.',
        'Deployment budgets are shown separately and can include invested capital; do not subtract them from cash a second time.',
        'ETF constituents, historical correlations, taxes, and future price changes are not inferred. This is not a funding or execution approval.']
    return {'local_pending_buys':pending,'scheduled_buys':scheduled,'deployment_budgets':budgets,
        'cash_after_known_commitments_usd':str(cash),'cash_coverage':'unknown' if result['cash_coverage']=='unknown' else 'insufficient' if cash<0 else 'covered_before_fees',
        'limitations':limitations}

def create_desk_router(sessions, broker_resolver, app):
    desk=Desk(sessions);app.state.research_desk=desk
    router=APIRouter(prefix='/api/discover/desk', tags=['Research desk'])
    @router.get('/status')
    def status(): return {'worker':desk.worker,'monitor_interval_hours':24,'execution_authority':False}
    @router.get('/records/{kind}')
    def records(kind: str, symbol: str|None=None):
        if kind not in {'company','monitor','review','experiment','allocation'}: raise HTTPException(404)
        return {'records':desk.rows(kind,symbol)}
    @router.post('/company/{symbol}')
    def collect(symbol: Symbol): return desk.collect(symbol)
    @router.post('/screen')
    def run_screen(request:ScreenRequest):
        results=[]
        for symbol in dict.fromkeys(request.symbols):
            row=desk.collect(symbol)
            results.append({'snapshot':row,'screen':screen(row['payload'],request.min_growth,request.min_margin,request.require_fcf)})
        return {'results':results,'scope':'Only the requested symbols; unknown facts do not pass. Strictly greater-than thresholds.'}
    @router.post('/monitors')
    def monitor(request:ThesisRequest):
        row=desk.get(request.snapshot_id,'company')
        if len(desk.rows('monitor',limit=101))>=100: raise HTTPException(409,'Monitor capacity reached')
        return desk.save('monitor',row['symbol'],{**request.model_dump(),'active':True})
    @router.post('/monitors/{identifier}/toggle')
    def toggle(identifier:str):
        with sessions() as session:
            row=session.get(DeskRecord,identifier)
            if row is None or row.kind!='monitor':raise HTTPException(404)
            row.payload={**row.payload,'active':not row.payload['active']};session.add(row);session.commit()
            return row.model_dump()
    @router.post('/monitors/{identifier}/review')
    def review(identifier:str):
        if not desk.review_lock.acquire(blocking=False): raise HTTPException(409,'A thesis review is already running')
        try: return desk.review(desk.get(identifier,'monitor'))
        finally: desk.review_lock.release()
    @router.get('/trial')
    def trial():
        from scripts.research.report_paper_trial import build_report
        database=sessions.kw['bind'].url.database
        try: return build_report(Path('.research-artifacts/paper-trial/trial-plan.json'),Path(database))
        except (ValueError,FileNotFoundError,KeyError): raise HTTPException(409,'Paper trial report unavailable for this database or plan')
    @router.post('/allocation')
    def allocation(request:AllocationRequest):
        try:
            snapshot=broker_resolver().paper_snapshot()
            result=portfolio_impact(snapshot,request)
            result.update(local_portfolio_context(sessions,snapshot,request,result))
        except Exception: raise HTTPException(409,'A complete paper account snapshot could not be read. No allocation was created.')
        return desk.save('allocation',request.symbol,result)
    @router.post('/experiment')
    def experiment():
        from tradingagents.ui.exploratory_replay import run_development
        # A fixed, hashed experiment is idempotent; negative outcomes are retained.
        with desk.review_lock:
            try: result=run_development(sessions)
            except Exception:
                result={'state':'failed','promotion_eligible':False,'message':'Development replay failed; inspect data assumptions and server tests before retrying.'}
            if result.get('manifest_hash'):
                previous=next((r for r in desk.rows('experiment') if r['payload'].get('manifest_hash')==result['manifest_hash']),None)
                if previous: return previous
            return desk.save('experiment','',result)
    stop=asyncio.Event();task=None
    @on_lifecycle(app, 'startup')
    async def start():
        nonlocal task
        async def run():
            while not stop.is_set():
                await asyncio.to_thread(desk.due)
                try: await asyncio.wait_for(stop.wait(),timeout=60)
                except asyncio.TimeoutError: pass
        task=asyncio.create_task(run())
    @on_lifecycle(app, 'shutdown')
    async def shutdown():
        stop.set();desk.worker['state']='stopped'
        if task:
            try: await asyncio.wait_for(task,timeout=5)
            except (asyncio.TimeoutError,asyncio.CancelledError): task.cancel()
    return router
