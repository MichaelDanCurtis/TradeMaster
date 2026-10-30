"""Bounded company discovery and decision-before-reveal historical rehearsal.

Uses the desk's immutable company snapshots and the Forecast Lab's GET-only capture.
Research stays separate from execution. Historical assessments reuse the bounded
Codex brief service only on explicit request.
"""
from __future__ import annotations

from tradingagents.ui.lifecycle import on_lifecycle

import asyncio
from datetime import date, timedelta
from pathlib import Path
import threading
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlmodel import select

from tradingagents.ui.company_evidence import finite, screen
from tradingagents.ui.forecast_data import capture, NY
from tradingagents.ui.models import now_utc
from tradingagents.ui.research_desk import DeskRecord, Symbol
from tradingagents.research.data.store import ArtifactStore

# An editable starting basket, deliberately not labeled a complete market universe.
STARTER = 'AAPL MSFT NVDA AMD GOOGL META AMZN ORCL CRM ADBE JPM BAC GS V MA UNH JNJ LLY MRK ABBV XOM CVX CAT DE HON GE COST WMT HD PG KO PEP'.split()


class ScanRequest(BaseModel):
    symbols: list[Symbol] = Field(min_length=1, max_length=500)
    min_growth: float = Field(default=10, ge=-100, le=1000, allow_inf_nan=False)
    min_margin: float = Field(default=0, ge=-1000, le=100, allow_inf_nan=False)
    require_fcf: bool = True


class TriageRequest(BaseModel):
    scan_id: str
    symbol: Symbol
    state: Literal['new', 'investigate', 'watch', 'dismissed']
    note: str = Field(default='', max_length=2000)


class ReplayRequest(BaseModel):
    symbol: Symbol
    cutoff: date
    horizon: int = Field(default=20, ge=1, le=60)
    feed: Literal['sip', 'iex'] = 'sip'
    source_scan_id: str | None = None
    evidence_mode: Literal["price", "filings"] = "price"


class DecisionRequest(BaseModel):
    expected_step: int = Field(ge=0, le=60)
    decision: Literal['investigate', 'watch', 'pass']
    thesis: str = Field(min_length=10, max_length=2000)
    invalidation: str = Field(min_length=10, max_length=2000)

    @field_validator('thesis', 'invalidation')
    @classmethod
    def meaningful(cls, value):
        value = value.strip()
        if len(value) < 10:
            raise ValueError('Please write at least 10 characters')
        return value


def rank_candidate(current, prior, request, asof):
    """Rank observed research reasons, never predicted investment returns."""
    packet = current['payload']
    identity_changed = bool(prior and prior['payload'].get('cik') != packet.get('cik'))
    if identity_changed:
        prior = None
    old = prior['payload'] if prior else None
    checks = screen(packet, request.min_growth, request.min_margin, request.require_fcf)
    reasons = []
    if checks['state'] == 'pass':
        reasons.append({'kind': 'quality', 'text': 'Passes all selected financial thresholds.'})
    if old:
        for metric, title in [('revenue_growth', 'Revenue growth'), ('net_margin', 'Net margin')]:
            before, after = finite(old.get('metrics', {}).get(metric)), finite(packet.get('metrics', {}).get(metric))
            if before is not None and after is not None and after > before:
                reasons.append({'kind': 'change', 'text': f'{title} estimate increased from {before:g}% to {after:g}% since the previous capture. Underlying provider as-of dates may be unknown.'})
        before, after = old.get('financials', {}).get('free_cash_flow'), packet.get('financials', {}).get('free_cash_flow')
        if before and after and finite(before.get('value')) is not None and finite(after.get('value')) is not None and after['value'] > before['value']:
            reasons.append({'kind': 'change', 'text': f'Annual free cash flow increased from ${before["value"]:,.0f} ({before.get("end", "undated")}) to ${after["value"]:,.0f} ({after.get("end", "undated")}). May reflect a new period or restatement.'})
    old_filings = {f['accession'] for f in old.get('filings', [])} if old else set()
    filings = []
    for filing in packet.get('filings', []):
        try:
            age = (asof - date.fromisoformat(filing['filed'])).days
        except (ValueError, KeyError):
            continue
        if 0 <= age <= 30 and filing['accession'] not in old_filings:
            filings.append(filing)
    if filings:
        reasons.append({'kind': 'filing', 'text': f'{len(filings)} recent filing(s) ' + ('new since the previous capture.' if old else 'in the first capture. Significance has not been assessed.')})
    gaps = list(packet.get('gaps', []))
    if identity_changed:
        gaps.append('The previous capture has a different or missing SEC issuer identity; financial comparisons were excluded.')
    if not old:
        gaps.append('First capture: changes in fundamentals cannot yet be measured.')
    if packet.get('security_type') != 'common_stock':
        gaps.append('Common-stock share class is not verified; review the instrument before researching it as stock.')
    return {'symbol': current['symbol'], 'snapshot_id': current['id'], 'previous_snapshot_id': prior['id'] if prior else None,
            'name': packet.get('profile', {}).get('name') or packet.get('sec_name') or current['symbol'],
            'collected_at': current['created_at'], 'screen': checks, 'reasons': reasons,
            'priority': len(reasons), 'filings': filings, 'gaps': gaps, 'sources': packet.get('sources', []),
            'security_type': packet.get('security_type', 'unverified')}


class OpportunityLab:
    def __init__(self, desk, resolver, root=None):
        self.desk, self.resolver = desk, resolver
        self.store = ArtifactStore(root or Path('.research-artifacts/opportunities/objects'))
        self.lock = threading.RLock()
        self.stopping = threading.Event()

    def update(self, identifier, payload):
        with self.desk.sessions() as session:
            row = session.get(DeskRecord, identifier)
            row.payload = payload
            session.add(row)
            session.commit()
            return row.model_dump()

    def recover(self, reset_stop=True):
        if reset_stop:
            self.stopping.clear()
        with self.desk.sessions() as session:
            for row in session.exec(select(DeskRecord).where(DeskRecord.kind == 'opportunity_scan')):
                if row.payload['state'] in {'running', 'queued'}:
                    row.payload = {**row.payload, 'state': 'interrupted', 'active_symbol': None}
                    session.add(row)
            for row in session.exec(select(DeskRecord).where(DeskRecord.kind == 'replay_evidence')):
                if row.payload.get('state') == 'collecting':
                    row.payload = {**row.payload, 'state': 'interrupted', 'message': 'Historical collection interrupted; retry explicitly.'}
                    session.add(row)
            session.commit()

    def start_scan(self, request, *, recipe=None):
        with self.lock:
            if any(r['payload']['state'] in {'running', 'queued'} for r in self.desk.rows('opportunity_scan', limit=100)):
                raise HTTPException(409, 'A company scan is already in progress')
            return self.desk.save('opportunity_scan', '', {'state': 'queued', 'request': request.model_dump(),
                'symbols': list(dict.fromkeys(request.symbols)), 'results': [], 'failures': [],
                'active_symbol': None, 'processed': 0, 'execution_authority': False,
                'recipe_id': recipe['id'] if recipe else None,
                'recipe_hash': recipe['payload']['artifact_hash'] if recipe else None,
                'membership': recipe['payload']['membership'] if recipe else {}})

    def tick(self):
        """One company per tick; partial results survive shutdown and failures."""
        with self.lock:
            scan = next((r for r in self.desk.rows('opportunity_scan', limit=100) if r['payload']['state'] in {'queued', 'running'}), None)
            if scan is None or self.stopping.is_set():
                return
            p = scan['payload']
            symbol = p['symbols'][p['processed']]
            self.update(scan['id'], {**p, 'state': 'running', 'active_symbol': symbol})
        # No database write transaction or service lock spans source requests.
        try:
            prior = next(iter(self.desk.rows('company', symbol, limit=1)), None)
            current = self.desk.collect(symbol)
            member = p.get('membership', {}).get(symbol)
            if member and current['payload'].get('cik') != member['cik']:
                raise ValueError('Collected issuer differs from frozen SEC directory')
            result = rank_candidate(current, prior, ScanRequest.model_validate(p['request']), now_utc().date())
            if member:
                result['directory_membership'] = member
                result['recipe_hash'] = p['recipe_hash']
            p['results'].append(result)
        except Exception:
            p['failures'].append({'symbol': symbol, 'message': 'Company collection failed. No inferred result was substituted.'})
        with self.lock:
            # Cancellation is respected after the in-flight read; retain its evidence.
            latest = self.desk.get(scan['id'], 'opportunity_scan')['payload']
            p['processed'] += 1
            p['active_symbol'] = None
            p['state'] = latest['state'] if latest['state'] == 'canceled' else 'interrupted' if self.stopping.is_set() else 'completed' if p['processed'] == len(p['symbols']) else 'running'
            p['results'].sort(key=lambda r: (-r['priority'], r['symbol']))
            self.update(scan['id'], p)

    def cancel(self, identifier):
        with self.lock:
            row = self.desk.get(identifier, 'opportunity_scan')
            if row['payload']['state'] in {'queued', 'running'}:
                return self.update(identifier, {**row['payload'], 'state': 'canceled'})
            return row

    def resume(self, identifier):
        with self.lock:
            row = self.desk.get(identifier, 'opportunity_scan')
            p = row['payload']
            if p['state'] not in {'canceled', 'interrupted'} or p.get('active_symbol'):
                raise HTTPException(409, 'Wait for the current read to finish before resuming a stopped scan')
            if p['processed'] >= len(p['symbols']):
                raise HTTPException(409, 'All symbols have already been processed')
            if any(r['payload']['state'] in {'running', 'queued'} for r in self.desk.rows('opportunity_scan', limit=100)):
                raise HTTPException(409, 'A company scan is already in progress')
            if p.get('recipe_id'):
                recipe = self.catalog.recipe(p['recipe_id'])
                if recipe['payload']['artifact_hash'] != p['recipe_hash']:
                    raise HTTPException(409, 'The preserved screening recipe changed')
            return self.update(identifier, {**p, 'state': 'queued', 'resumed_at': now_utc().isoformat()})

    def triage(self, request):
        scan = self.desk.get(request.scan_id, 'opportunity_scan')
        if not any(r['symbol'] == request.symbol for r in scan['payload']['results']):
            raise HTTPException(422, 'Select a company from this scan')
        return self.desk.save('opportunity_triage', request.symbol, request.model_dump())

    def create_replay(self, request):
        now = now_utc()
        if request.cutoff >= now.astimezone(NY).date():
            raise HTTPException(422, 'Choose a completed historical exchange session')
        if request.source_scan_id:
            scan = self.desk.get(request.source_scan_id, 'opportunity_scan')
            if request.symbol not in [r['symbol'] for r in scan['payload']['results']]:
                raise HTTPException(422, 'The company is not in the linked scan')
        provider, _ = self.resolver()
        end = min(request.cutoff + timedelta(days=request.horizon * 2 + 15), now.astimezone(NY).date() - timedelta(days=1))
        data = capture(provider, self.store, request.symbol, request.cutoff - timedelta(days=150), end, request.feed, False, now)
        dates = [r['date'] for r in data['calendar'] if r['date'] <= end.isoformat()]
        cutoff = request.cutoff.isoformat()
        if cutoff not in dates:
            raise HTTPException(422, 'Cutoff must be an exchange session, not a weekend or holiday')
        index = dates.index(cutoff)
        history, targets = dates[max(0, index - 59):index + 1], dates[index + 1:index + 1 + request.horizon]
        if len(history) < 60 or len(targets) < request.horizon:
            raise HTTPException(422, 'This date needs 60 context sessions and the full completed reveal horizon')
        if any(d not in data['bars'][request.symbol] for d in history + targets):
            raise HTTPException(422, 'Missing required bars; choose another period or feed. No gap filling is permitted.')
        digest = self.store.put_json(data)
        row = self.desk.save('decision_replay', request.symbol, {'request': request.model_dump(mode='json'),
            'capture_hash': digest, 'history_dates': history, 'target_dates': targets, 'step': 0, 'decisions': []})
        return self.replay_view(row)

    def replay_view(self, row):
        p = row['payload']
        data = self.store.json(p['capture_hash'])
        visible = p['history_dates'] + p['target_dates'][:p['step']]
        bars = [{'date': d, **data['bars'][row['symbol']][d]} for d in visible]
        start = data['bars'][row['symbol']][p['history_dates'][-1]]['close']
        from tradingagents.ui.historical_replay import evidence_view
        historical = evidence_view(self, row['id'], p['step']) if p['request'].get('evidence_mode') == 'filings' else None
        return {'evidence_mode': p['request'].get('evidence_mode', 'price'), 'historical_evidence': historical, 'id': row['id'], 'symbol': row['symbol'], 'created_at': row['created_at'],
                'cutoff': p['request']['cutoff'], 'visible_through': visible[-1], 'step': p['step'],
                'horizon': len(p['target_dates']), 'complete': p['step'] == len(p['target_dates']),
                'bars': bars, 'decisions': p['decisions'], 'source_scan_id': p['request'].get('source_scan_id'),
                'revealed_price_change_pct': (bars[-1]['close'] / start - 1) * 100 if p['step'] else None,
                'feed': data['feed'], 'captured_at': data['observed_at'], 'capture_hash': p['capture_hash'],
                'limitations': ['Historical price rehearsal using today’s split-adjusted data; revisions and hindsight remain possible.',
                    'Current company metrics, briefs, and model forecasts are excluded from this historical view.',
                    'Price changes exclude dividends, fees, slippage and trading decisions; they are not strategy returns.',
                    'Each decision is saved before one more session is revealed. This local rehearsal is not a blind research holdout.']}

    def advance(self, identifier, request):
        with self.lock:
            row = self.desk.get(identifier, 'decision_replay')
            p = row['payload']
            if request.expected_step != p['step']:
                raise HTTPException(409, 'This replay changed. Reload before recording another decision.')
            if p['step'] >= len(p['target_dates']):
                raise HTTPException(409, 'The replay is complete')
            # Verify artifacts before persisting a decision or moving the cursor.
            view = self.replay_view(row)
            assessment = None
            if p['request'].get('evidence_mode') == 'filings':
                from tradingagents.ui.historical_replay import assessment_receipt
                assessment = assessment_receipt(self, identifier, p['step'])
            decision = {**({'historical_assessment': assessment} if assessment else {}), **request.model_dump(), 'recorded_at': now_utc().isoformat(), 'visible_through': view['visible_through']}
            receipt = self.store.put_json({'replay_id': identifier, 'capture_hash': p['capture_hash'], **decision})
            p = {**p, 'step': p['step'] + 1, 'decisions': [*p['decisions'], {**decision, 'receipt_hash': receipt}]}
            return self.replay_view(self.update(identifier, p))


def create_opportunity_router(desk, resolver, app):
    lab = OpportunityLab(desk, resolver)
    app.state.opportunity_lab = lab
    router = APIRouter(prefix='/api/discover/opportunities', tags=['Opportunity inbox'])
    task = None

    @on_lifecycle(app, 'startup')
    async def startup():
        nonlocal task
        lab.recover()
        async def loop():
            while not lab.stopping.is_set():
                try:
                    await asyncio.to_thread(lab.tick)
                except Exception:
                    # No silent automatic restart of a failed scan.
                    lab.recover(reset_stop=False)
                await asyncio.sleep(1)
        task = asyncio.create_task(loop())

    @on_lifecycle(app, 'shutdown')
    async def shutdown():
        lab.stopping.set()
        if task:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @router.get('')
    def inbox():
        return {'starter_symbols': STARTER, 'scans': desk.rows('opportunity_scan', limit=20),
                'triage': desk.rows('opportunity_triage', limit=1000),
                'replays': [{'id': r['id'], 'symbol': r['symbol'], 'cutoff': r['payload']['request']['cutoff'],
                    'step': r['payload']['step'], 'horizon': len(r['payload']['target_dates'])} for r in desk.rows('decision_replay')],
                'scope': 'Editable basket of up to 500 symbols. This is not a whole-market scan. Priority counts research reasons, not expected returns.'}

    from tradingagents.ui.discovery_catalog import install_catalog_routes
    install_catalog_routes(router, lab)

    @router.post('/scans')
    def scan(request: ScanRequest):
        return lab.start_scan(request)

    @router.post('/scans/{identifier}/cancel')
    def cancel(identifier: str):
        return lab.cancel(identifier)

    @router.post('/scans/{identifier}/resume')
    def resume(identifier: str):
        return lab.resume(identifier)

    @router.post('/triage')
    def triage(request: TriageRequest):
        return lab.triage(request)

    @router.post('/replays')
    def replay(request: ReplayRequest):
        try:
            return lab.create_replay(request)
        except (ValueError, OSError):
            raise HTTPException(409, 'Historical capture failed. Check the market-data connection and chosen feed; no replay was created.')

    @router.get('/replays/{identifier}')
    def get_replay(identifier: str):
        return lab.replay_view(desk.get(identifier, 'decision_replay'))

    @router.post('/replays/{identifier}/advance')
    def advance(identifier: str, request: DecisionRequest):
        return lab.advance(identifier, request)

    from tradingagents.ui.historical_replay import install_routes
    install_routes(router, lab)
    return router
