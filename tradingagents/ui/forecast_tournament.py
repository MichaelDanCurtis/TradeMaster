"""Frozen, bounded TimesFM development tournaments using the existing job runner."""
from __future__ import annotations

from tradingagents.ui.lifecycle import on_lifecycle

import asyncio
import hashlib
import statistics
import threading
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlmodel import select

from tradingagents.ui.forecast_lab import ForecastRequest, ForecastJob, ACTIVE, ROOT
from tradingagents.ui.models import now_utc
from tradingagents.ui.research_desk import Symbol, DeskRecord


class TournamentRequest(BaseModel):
    symbols: list[Symbol] = Field(min_length=1, max_length=6)
    horizons: list[Literal[5, 20]] = Field(default_factory=lambda: [5, 20], min_length=1, max_length=2)
    inputs: Literal['stock', 'compare'] = 'compare'
    device: Literal['cpu', 'mps', 'mlx'] = 'cpu'
    feed: Literal['sip', 'iex'] = 'sip'
    request_key: str = Field(min_length=8, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')

    @model_validator(mode='after')
    def qualified(self):
        self.symbols = sorted(set(self.symbols))
        self.horizons = sorted(set(self.horizons))
        return self


def condition(values):
    """Fixed descriptive bins using only the trailing context, never outcomes."""
    change = values[-1] / values[-61] - 1
    returns = [b / a - 1 for a, b in zip(values[-21:-1], values[-20:])]
    vol = statistics.stdev(returns) * (252 ** .5)
    trend = 'rising' if change > .05 else 'falling' if change < -.05 else 'sideways'
    return {'label': trend + (' / high volatility' if vol >= .40 else ' / lower volatility'),
            'trailing_60_return_pct': change * 100, 'trailing_20_annualized_vol_pct': vol * 100}


def case_rows(result, job_id):
    if len(result['cases']) != len(result['metrics']) or len(result['cases']) != len(result['runtime']['results']):
        raise ValueError('Incomplete forecast case metrics')
    rows = []
    for c, m, prediction in zip(result['cases'], result['metrics'], result['runtime']['results']):
        scale = c['values'][-1]
        rows.append({'job_id': job_id, 'symbol': result['symbol'], 'horizon': result['horizon'],
            'variant': c['variant'], 'cutoff': c['cutoff'], 'targets': c['target_dates'],
            'condition': condition(c['values']), 'observations': m['observations'],
            'mae_pct': m['mae_usd'] / scale * 100, 'flat_mae_pct': m['baseline_mae_usd'] / scale * 100,
            'drift_mae_pct': m['drift_mae_usd'] / scale * 100, 'coverage_pct': m['interval_coverage_pct'],
            'band_width_pct': m['mean_interval_width_usd'] / scale * 100,
            'interval_score_pct': m['interval_score_usd'] / scale * 100,
            'inference_seconds': prediction['inference_seconds'], 'mae_usd': m['mae_usd'],
            'input_hash': result['input_hash'], 'prediction_hash': result['prediction_hash']})
    return rows


def leaderboard(cases):
    """Equal weight per stock/window, separate horizons; never average raw dollars."""
    output = []
    keys = sorted({(c['horizon'], c['variant']) for c in cases})
    for horizon, variant in keys:
        group = [c for c in cases if (c['horizon'], c['variant']) == (horizon, variant)]
        for label in ['all', *sorted({c['condition']['label'] for c in group})]:
            selected = [c for c in group if label == 'all' or c['condition']['label'] == label]
            avg = lambda key: statistics.mean(c[key] for c in selected)
            flat, drift, model = avg('flat_mae_pct'), avg('drift_mae_pct'), avg('mae_pct')
            output.append({'horizon': horizon, 'variant': variant, 'condition': label, 'windows': len(selected),
                'symbols': len({c['symbol'] for c in selected}), 'observations': sum(c['observations'] for c in selected),
                'mae_pct': model, 'flat_mae_pct': flat, 'drift_mae_pct': drift,
                'improvement_vs_flat_pct': (1 - model / flat) * 100 if flat else None,
                'improvement_vs_drift_pct': (1 - model / drift) * 100 if drift else None,
                'wins_vs_flat': sum(c['mae_pct'] < c['flat_mae_pct'] for c in selected),
                'wins_vs_drift': sum(c['mae_pct'] < c['drift_mae_pct'] for c in selected),
                'coverage_pct': avg('coverage_pct'), 'band_width_pct': avg('band_width_pct'),
                'interval_score_pct': avg('interval_score_pct'), 'inference_seconds': avg('inference_seconds')})
    return output


class Tournament:
    def __init__(self, desk, lab):
        self.desk, self.lab = desk, lab
        self.lock = threading.RLock()
        self.stop = threading.Event()

    def pins(self, device):
        runtime = self.lab.runtime()
        if runtime['state'] != 'installed':
            raise HTTPException(409, runtime['message'])
        manifest = runtime['manifest']
        files = ['tradingagents/ui/forecast_data.py', 'tradingagents/ui/forecast_lab.py',
                 'tradingagents/ui/forecast_tournament.py', 'scripts/research/' + ('forecast_mlx_child.py' if device == 'mlx' else 'forecast_child.py')]
        return {'model': {k: manifest[k] for k in ['model_id', 'revision', 'code_revision', 'files']},
                'code': {p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in files}}

    def update(self, identifier, payload):
        with self.desk.sessions() as s:
            row = s.get(DeskRecord, identifier)
            row.payload = payload
            s.add(row); s.commit()
            return row.model_dump()

    def submit(self, request):
        with self.lock:
            with self.desk.sessions() as s:
                old = s.exec(select(DeskRecord).where(DeskRecord.kind == 'forecast_tournament',
                    DeskRecord.payload['request']['request_key'].as_string() == request.request_key)).first()
                if old:
                    if old.payload['request'] != request.model_dump():
                        raise HTTPException(409, 'This key belongs to a different tournament definition')
                    return old.model_dump()
            if any(r['payload']['state'] in {'queued', 'running'} for r in self.desk.rows('forecast_tournament', limit=100)):
                raise HTTPException(409, 'A tournament is already active')
            pins = self.pins(request.device)
            if request.device == 'mlx' and not self.lab.runtime().get('mlx', {}).get('installed'):
                raise HTTPException(409, 'The optional MLX environment is not installed')
            recipe = {'schema': 'timesfm_tournament_v1', 'request': request.model_dump(), 'pins': pins,
                'frozen_at': now_utc().isoformat(), 'period': '2022 context; three 20-session-spaced windows in late 2023',
                'scoring': 'Equal stock/window weights; MAE divided by final context close; horizons kept separate.',
                'conditions': 'Trailing 60-session return: rising >5%, falling <-5%, otherwise sideways. Trailing 20 daily-return sample volatility annualized sqrt(252): high >=40%.',
                'evidence_scope': 'Exploratory reconstruction, not a holdout; model pretraining overlap unknown. No strategy return or promotion.'}
            recipe_hash = self.lab.store.put_json(recipe)
            return self.desk.save('forecast_tournament', '', {'request': request.model_dump(), 'recipe_hash': recipe_hash,
                'pins': pins, 'state': 'queued', 'message': 'Waiting for the local forecast runner',
                'cells': [{'symbol': symbol, 'horizon': horizon, 'state': 'pending', 'job_id': None, 'error': None}
                    for symbol in request.symbols for horizon in request.horizons], 'cases': [], 'finished_at': None})

    def recover(self):
        with self.lock:
            for row in self.desk.rows('forecast_tournament', limit=100):
                if row['payload']['state'] in {'queued', 'running'}:
                    # Recover a child submitted just before a lost parent update.
                    # Lookup only: restart never launches another model process.
                    for index, cell in enumerate(row['payload']['cells']):
                        if not cell['job_id']:
                            with self.desk.sessions() as session:
                                job = session.exec(select(ForecastJob).where(ForecastJob.request_key == f'tournament_{row["id"]}_{index}')).first()
                                if job:
                                    cell.update(job_id=job.id, state=job.state, error=job.error)
                    self.update(row['id'], {**row['payload'], 'state': 'interrupted',
                        'message': 'API restarted; preserved child jobs can be inspected. No automatic resubmission.'})

    def cancel(self, identifier):
        with self.lock:
            row = self.desk.get(identifier, 'forecast_tournament')
            if row['payload']['state'] in {'queued', 'running'}:
                return self.update(identifier, {**row['payload'], 'state': 'canceled',
                    'message': 'No more jobs will launch. Any in-flight child is allowed to finish and remains in the Forecast Lab.'})
            return row

    def tick(self):
        with self.lock:
            row = next((r for r in self.desk.rows('forecast_tournament', limit=100) if r['payload']['state'] in {'queued', 'running'}), None)
            if row is None or self.stop.is_set(): return
            p = row['payload']
            try:
                if self.pins(p['request']['device']) != p['pins']:
                    raise ValueError('Model or scoring code changed since the tournament was frozen')
                for index, cell in enumerate(p['cells']):
                    if cell['state'] in {'completed', 'failed', 'interrupted'}: continue
                    if not cell['job_id']:
                        req = ForecastRequest(symbol=cell['symbol'], horizon=cell['horizon'],
                            inputs=p['request']['inputs'], mode='development', device=p['request']['device'],
                            feed=p['request']['feed'], request_key=f'tournament_{row["id"]}_{index}')
                        # Stable key recovers the same child after uncertain publication.
                        try: job = self.lab.submit(req)
                        except HTTPException as exc:
                            if exc.status_code == 409 and any(j['state'] in ACTIVE for j in self.lab.rows()):
                                p['message'] = 'Waiting for the existing local forecast job'; self.update(row['id'], p); return
                            raise
                        cell.update(job_id=job['id'], state=job['state'])
                        p.update(state='running', message=f'{cell["symbol"]} · {cell["horizon"]} sessions')
                        self.update(row['id'], p)
                        return
                    job = self.lab.detail(cell['job_id'])
                    if job['state'] in ACTIVE:
                        cell['state'] = job['state']; self.update(row['id'], p); return
                    cell['state'] = job['state']
                    if job['state'] == 'completed':
                        result = job['result']
                        if {k: result['model'][k] for k in p['pins']['model']} != p['pins']['model']:
                            raise ValueError('Completed child used a different model manifest')
                        # All horizons for a symbol must use identical normalized data.
                        data_hash = self.lab.store.put_json({'bars': result['bars'], 'calendar': result['calendar'], 'feed': result['feed']})
                        previous = [c.get('data_hash') for c in p['cells'] if c['symbol'] == cell['symbol'] and c.get('data_hash')]
                        if previous and data_hash not in previous:
                            cell.update(state='failed', error='Historical data changed between horizons; results excluded from the tournament.')
                        else:
                            p['cases'].extend(case_rows(result, job['id']))
                            cell.update(data_hash=data_hash, result_hash=job['result_hash'])
                    else:
                        cell['error'] = job['error'] or 'Child forecast did not complete'
                    self.update(row['id'], p)
                terminal = all(c['state'] in {'completed', 'failed', 'interrupted'} for c in p['cells'])
                if terminal:
                    p.update(state='completed' if all(c['state'] == 'completed' for c in p['cells']) else 'completed_with_failures',
                             message='All planned jobs settled; inspect coverage and retained failures.', finished_at=now_utc().isoformat())
                    p['summary_hash'] = self.lab.store.put_json({'recipe_hash': p['recipe_hash'], 'cells': p['cells'], 'cases': p['cases'], 'leaderboard': leaderboard(p['cases'])})
                    self.update(row['id'], p)
            except Exception as exc:
                self.update(row['id'], {**p, 'state': 'interrupted', 'message': str(exc) if isinstance(exc, ValueError) else 'Tournament stopped after an unexpected error; child receipts are preserved.', 'finished_at': now_utc().isoformat()})

    def detail(self, identifier):
        row = self.desk.get(identifier, 'forecast_tournament')
        p = row['payload']
        recipe = self.lab.store.json(p['recipe_hash'])
        children = {}
        for cell in p['cells']:
            if cell['job_id']:
                job = self.lab.get(cell['job_id'])
                children[job['id']] = {k: job[k] for k in ['state', 'error']}

        return {**row, 'recipe': recipe, 'child_statuses': children, 'leaderboard': leaderboard(p['cases']),
                'coverage_complete': p['state'] == 'completed' and all(c['state'] == 'completed' for c in p['cells'])}


def create_tournament_router(desk, lab, app):
    tournament = Tournament(desk, lab)
    app.state.forecast_tournament = tournament
    router = APIRouter(prefix='/api/discover/forecast/tournaments', tags=['Forecast tournament'])
    task = None
    @on_lifecycle(app, 'startup')
    async def start():
        nonlocal task
        tournament.recover()
        async def loop():
            while not tournament.stop.is_set():
                await asyncio.to_thread(tournament.tick)
                await asyncio.sleep(2)
        task = asyncio.create_task(loop())
    @on_lifecycle(app, 'shutdown')
    async def stop():
        tournament.stop.set()
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    @router.get('')
    def listing():
        return {'tournaments': desk.rows('forecast_tournament', limit=30)}
    @router.post('', status_code=202)
    def submit(request: TournamentRequest): return tournament.submit(request)
    @router.get('/{identifier}')
    def detail(identifier: str): return tournament.detail(identifier)
    @router.post('/{identifier}/stop')
    def cancel(identifier: str): return tournament.cancel(identifier)
    @router.get('/{identifier}/export.json')
    def export(identifier: str):
        import json
        return Response(json.dumps(tournament.detail(identifier), indent=2), media_type='application/json',
            headers={'Content-Disposition': 'attachment; filename="forecast-tournament.json"'})
    return router
