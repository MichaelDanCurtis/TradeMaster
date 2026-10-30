"""Local research jobs with immutable source/output artifacts and no order interface."""
from __future__ import annotations

from tradingagents.ui.lifecycle import on_lifecycle

from datetime import date, datetime, time, timedelta, timezone
import asyncio
import csv
import hashlib
import io
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import threading
import zipfile
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field as PF, StrictBool
from sqlalchemy import Column, JSON, Index, text, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import SQLModel, Field, select

from tradingagents.research.data.store import ArtifactStore
from tradingagents.ui.models import now_utc, new_id
from tradingagents.ui.research_desk import Symbol
from tradingagents.ui.forecast_data import NY, capture, experiment_cases, comparison_summary, metrics, score_saved, validate_output

ROOT = Path(__file__).resolve().parents[2]
ACTIVE = ('queued', 'collecting', 'running')


class ForecastJob(SQLModel, table=True):
    __tablename__ = 'ui_forecast_jobs'
    __table_args__ = (Index('one_active_forecast', 'active_slot', unique=True,
                           sqlite_where=text("state IN ('queued','collecting','running')")),)
    id: str = Field(default_factory=lambda: new_id('forecast'), primary_key=True)
    request_key: str = Field(unique=True, index=True)
    active_slot: int = 1
    state: str = 'queued'
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    updated_at: str = Field(default_factory=lambda: now_utc().isoformat())
    request: dict = Field(sa_column=Column(JSON, nullable=False))
    input_hash: str | None = None
    result_hash: str | None = None
    error: str | None = None


class ForecastScore(SQLModel, table=True):
    __tablename__ = 'ui_forecast_scores'
    id: str = Field(default_factory=lambda: new_id('forecast_score'), primary_key=True)
    forecast_id: str = Field(index=True)
    created_at: str = Field(default_factory=lambda: now_utc().isoformat())
    artifact_hash: str


class ForecastRequest(BaseModel):
    symbol: Symbol
    horizon: Literal[5, 20] = 5
    inputs: Literal['stock', 'market_volume', 'compare'] = 'stock'
    mode: Literal['prospective', 'development'] = 'prospective'
    feed: Literal['sip', 'iex'] = 'sip'
    device: Literal['cpu', 'mps', 'mlx'] = 'cpu'
    request_key: str = PF(min_length=8, max_length=128, pattern=r'^[a-zA-Z0-9_-]+$')



class ForecastPreferences(SQLModel, table=True):
    __tablename__ = 'ui_forecast_preferences'
    id: str = Field(default='local', primary_key=True)
    auto_score: bool = True


class OutcomeSettings(BaseModel):
    enabled: StrictBool


class ForecastLab:
    def __init__(self, sessions, resolver, root=None):
        self.sessions, self.resolver = sessions, resolver
        self.root = Path(root) if root else ROOT/'.research-artifacts/forecast'
        self.store = ArtifactStore(self.root/'objects')
        self.closing = threading.Event()
        self.process = None
        self.thread = None
        self.lock = threading.Lock()
        self.score_lock = threading.Lock()
        self.outcome_worker = {'state': 'stopped', 'checked_at': None, 'error': None}

    def runtime(self):
        path = self.root/'runtime.json'
        if not path.exists() or not (ROOT/'.venv-timesfm/bin/python').exists():
            return {'state': 'not_installed', 'message': 'Run scripts/research/setup_forecast.sh and register_forecast_runtime.py on this computer'}
        try:
            manifest = json.loads(path.read_text())
            files = manifest['files']
            if (set(files) != {'model.safetensors', 'config.json', 'LICENSE'} or
                    any(not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest) for digest in files.values())):
                raise ValueError('Invalid model checksums')
            if not all((self.root/'model'/name).is_file() for name in manifest['files']):
                raise ValueError('Missing model files')
            return {'state': 'installed', 'manifest': manifest,
                    'mlx': {'installed': (ROOT/'.venv-timesfm-mlx/bin/python').is_file(),
                            'message': 'Optional MLX environment; Metal availability and pinned code are checked on each run'},
                    'message': 'Local files present; their checksums are verified before each run'}
        except (ValueError, KeyError, TypeError, OSError):
            return {'state': 'unavailable', 'message': 'Model manifest is incomplete'}

    def get(self, identifier):
        with self.sessions() as s:
            row = s.get(ForecastJob, identifier)
            if row is None:
                raise HTTPException(404, 'Forecast not found')
            return row.model_dump()

    def rows(self):
        with self.sessions() as s:
            return [r.model_dump() for r in s.exec(select(ForecastJob).order_by(ForecastJob.created_at.desc()).limit(50)).all()]

    def detail(self, identifier):
        row = self.get(identifier)
        row['result'] = self.store.json(row['result_hash']) if row['result_hash'] else None
        with self.sessions() as s:
            scores = s.exec(select(ForecastScore).where(ForecastScore.forecast_id == identifier).order_by(ForecastScore.created_at.desc())).all()
            row['scores'] = [{**r.model_dump(), 'result': self.store.json(r.artifact_hash)} for r in scores]
        return row

    def update(self, identifier, **values):
        with self.sessions() as s:
            changed = s.execute(update(ForecastJob).where(ForecastJob.id == identifier,
                ForecastJob.state.in_(ACTIVE)).values(**values, updated_at=now_utc().isoformat()))
            s.commit()
            return changed.rowcount == 1

    def recover(self):
        with self.sessions() as s:
            for row in s.exec(select(ForecastJob).where(ForecastJob.state.in_(ACTIVE))).all():
                row.state = 'interrupted'
                row.error = 'The API stopped before a completed forecast was saved. No automatic retry.'
                row.updated_at = now_utc().isoformat()
                s.add(row)
            s.commit()

    def submit(self, request, launch=True):
        with self.lock:
            with self.sessions() as s:
                old = s.exec(select(ForecastJob).where(ForecastJob.request_key == request.request_key)).first()
                if old:
                    if old.request != request.model_dump():
                        raise HTTPException(409, 'This request key belongs to different forecast settings')
                    return old.model_dump()
                if self.runtime()['state'] != 'installed':
                    raise HTTPException(409, self.runtime()['message'])
                if request.device == 'mlx' and not (ROOT/'.venv-timesfm-mlx/bin/python').is_file():
                    raise HTTPException(409, 'Install the optional MLX runtime with scripts/research/setup_forecast_mlx.sh')
                if self.closing.is_set():
                    raise HTTPException(503, 'Forecast service is stopping')
                row = ForecastJob(request_key=request.request_key, request=request.model_dump())
                try:
                    s.add(row); s.commit()
                except IntegrityError as exc:
                    s.rollback()
                    raise HTTPException(409, 'Another local forecast is already running') from exc
                saved = row.model_dump()
            if launch:
                self.thread = threading.Thread(target=self.run, args=(saved['id'],), daemon=True)
                self.thread.start()
            return saved

    def infer(self, packet, device):
        env = {k: v for k,v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'SYSTEMROOT')}
        env.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1', TOKENIZERS_PARALLELISM='false',
                   PYTORCH_ENABLE_MPS_FALLBACK='0', OMP_NUM_THREADS='8')
        with tempfile.TemporaryDirectory(prefix='forecast-') as temp:
            input_path, output_path = Path(temp)/'input.json', Path(temp)/'output.json'
            # Only model inputs enter the process, never outcomes, provider config, or credentials.
            input_path.write_text(json.dumps({'horizon': packet['horizon'], 'cases': [
                {'values': c['values'], 'covariates': c['covariates']} for c in packet['cases']]}))
            environment = '.venv-timesfm-mlx' if device == 'mlx' else '.venv-timesfm'
            runner = 'forecast_mlx_child.py' if device == 'mlx' else 'forecast_child.py'
            command = [str(ROOT/environment/'bin/python'), '-I', str(ROOT/'scripts/research'/runner),
                       str(input_path), str(output_path), str(self.root/'model'), '--device', device]
            with (Path(temp)/'stderr.log').open('w') as log:
                with self.lock:
                    if self.closing.is_set():
                        raise ValueError('Forecast service stopped')
                    self.process = subprocess.Popen(command, env=env, cwd=temp, stdout=log, stderr=log)
                try:
                    code = self.process.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    self.process.kill(); self.process.wait()
                    raise ValueError('Model exceeded the 180-second inference limit; process terminated')
                finally:
                    with self.lock:
                        self.process = None
            if code != 0:
                digest = self.store.put((Path(temp)/'stderr.log').read_bytes())
                raise ValueError(f'Local {device} inference failed; diagnostic receipt {digest}. No device fallback was attempted')
            output = json.loads(output_path.read_text())
            validate_output(output, packet['horizon'], len(packet['cases']))
            return output

    def run(self, identifier):
        try:
            job = self.get(identifier)
            if job['state'] not in ACTIVE:
                return
            request = job['request']
            manifest = self.runtime()['manifest']
            for name, expected in manifest['files'].items():
                with (self.root/'model'/name).open('rb') as f:
                    if hashlib.file_digest(f, 'sha256').hexdigest() != expected:
                        raise ValueError('Installed model checksum differs from its saved manifest')
            self.update(identifier, state='collecting')
            observed = now_utc()
            development = request['mode'] == 'development'
            end = date(2023, 12, 31) if development else observed.astimezone(NY).date()-timedelta(days=1)
            start = date(2022, 1, 1) if development else end-timedelta(days=550)
            provider, _ = self.resolver()
            data = capture(provider, self.store, request['symbol'], start, end,
                           request['feed'], request['inputs'] != 'stock', observed)
            cases = experiment_cases(data, request['horizon'], request['mode'], request['inputs'])
            packet = {**data, 'cases': cases, 'horizon': request['horizon'], 'mode': request['mode'],
                'model': manifest, 'request': request,
                'runner_sha256': hashlib.sha256((ROOT/'scripts/research'/
                    ('forecast_mlx_child.py' if request['device'] == 'mlx' else 'forecast_child.py')).read_bytes()).hexdigest()}
            input_hash = self.store.put_json(packet)
            if not self.update(identifier, input_hash=input_hash, state='running') or self.closing.is_set():
                return
            output = self.infer(packet, request['device'])
            # Publish the numerical prediction tied to its inputs before recording
            # issuance time. Result metadata and DB publication can follow later.
            prediction_hash = self.store.put_json({'input_hash': input_hash, 'runtime': output})
            issued = now_utc()
            next_session = next(s for s in data['calendar'] if s['date'] == cases[0]['target_dates'][0])
            opens = datetime.combine(date.fromisoformat(next_session['date']), time.fromisoformat(next_session['open']), NY)
            prospective = not development and issued < opens
            evaluated = [metrics(c,r,c['actual']) for c,r in zip(cases,output['results'])] if development else []
            result = {**packet, 'runtime': output, 'issued_at': issued.isoformat(),
                'prediction_hash': prediction_hash,
                'prospective_eligible': prospective, 'input_hash': input_hash,
                'evidence_scope': 'Exploratory 2023 replay; model pretraining overlap is unknown' if development else
                    'Forecast saved before the first target session opened' if prospective else
                    'Late issuance: the first target session already opened; excluded from prospective evidence',
                'metrics': evaluated, 'comparison': comparison_summary(cases, evaluated) if evaluated else [],
                'limitations': ['Price forecasts, not expected trading profit; fees and execution are not modeled.',
                    'The 10th–90th percentile band is a model output, not a calibrated 80% guarantee.',
                    'Inputs are split-adjusted USD daily closes, excluding the current New York calendar day. Dividends are not reinvested.',
                    'Current symbol identity and present-day data revisions are reconstruction assumptions.',
                    'Forecasts have no order, allocation, or strategy-promotion authority.']}
            self.update(identifier, state='completed', result_hash=self.store.put_json(result))
        except Exception as exc:
            # Provider exceptions can contain request details. Only our validated messages are exposed.
            message = str(exc) if isinstance(exc, ValueError) else f'{type(exc).__name__}: forecast could not complete; check the local runtime and data provider'
            self.update(identifier, state='failed', error=message)

    def score(self, identifier):
        with self.score_lock:
            return self._score(identifier)

    def _score(self, identifier):
        detail = self.detail(identifier)
        saved = detail['result']
        if not saved or saved['mode'] != 'prospective':
            raise HTTPException(409, 'Only a completed forward forecast can collect new outcomes')
        now = now_utc()
        target_end = saved['cases'][0]['target_dates'][-1]
        if now.astimezone(NY).date().isoformat() <= target_end:
            return {'state': 'pending', 'reason': 'The forecast horizon has not finished', 'target_end': target_end}
        for old in detail['scores']:
            if old['result']['state'] == 'scored':
                return old['result']
        provider, _ = self.resolver()
        fresh = capture(provider, self.store, saved['symbol'], date.fromisoformat(saved['cases'][0]['dates'][0]),
            date.fromisoformat(target_end), saved['feed'], False, now)
        result = {**score_saved(saved, fresh, now), 'observed_at': now.isoformat(),
                  'source_hash': self.store.put_json(fresh), 'forecast_hash': detail['result_hash'],
                  'prospective_eligible': saved['prospective_eligible']}
        digest = self.store.put_json(result)
        with self.sessions() as s:
            s.add(ForecastScore(forecast_id=identifier, artifact_hash=digest)); s.commit()
        return result

    def auto_score_enabled(self):
        with self.sessions() as s:
            row = s.get(ForecastPreferences, 'local')
            return row.auto_score if row else True

    def set_auto_score(self, enabled):
        with self.sessions() as s:
            row = s.get(ForecastPreferences, 'local') or ForecastPreferences()
            row.auto_score = enabled
            s.add(row); s.commit()
        return {'enabled': enabled}

    def score_due(self):
        """One matured forecast per tick; failed/missing-data captures back off 24h."""
        now = now_utc()
        self.outcome_worker = {'state': 'checking', 'checked_at': now.isoformat(), 'error': None}
        if not self.auto_score_enabled() or self.closing.is_set():
            self.outcome_worker['state'] = 'paused' if not self.closing.is_set() else 'stopped'
            return
        try:
            with self.sessions() as s:
                jobs = [r.model_dump() for r in s.exec(select(ForecastJob).where(
                    ForecastJob.state == 'completed').order_by(ForecastJob.created_at)).all()]
            for job in jobs:
                if job['request']['mode'] != 'prospective':
                    continue
                with self.sessions() as s:
                    last = s.exec(select(ForecastScore).where(ForecastScore.forecast_id == job['id'])
                                  .order_by(ForecastScore.created_at.desc())).first()
                if last:
                    previous = self.store.json(last.artifact_hash)
                    if previous['state'] in ('scored', 'basis_changed') or datetime.fromisoformat(last.created_at) > now-timedelta(hours=24):
                        continue
                saved = self.store.json(job['result_hash'])
                if saved['cases'][0]['target_dates'][-1] >= now.astimezone(NY).date().isoformat():
                    continue
                try:
                    self.score(job['id'])
                except Exception as exc:
                    reason = str(exc) if isinstance(exc, ValueError) else f'{type(exc).__name__}: outcome capture failed'
                    receipt = self.store.put_json({'state': 'failed', 'reason': reason,
                        'observed_at': now.isoformat(), 'forecast_hash': job['result_hash']})
                    with self.sessions() as s:
                        s.add(ForecastScore(forecast_id=job['id'], artifact_hash=receipt)); s.commit()
                    self.outcome_worker['error'] = reason
                self.outcome_worker['state'] = 'waiting'
                return
            self.outcome_worker['state'] = 'waiting'
        except Exception as exc:
            self.outcome_worker['state'] = 'error'
            self.outcome_worker['error'] = f'{type(exc).__name__}: saved outcome checks could not finish'

    def export_csv(self, identifier):
        detail = self.detail(identifier)
        saved = detail['result']
        if not saved:
            raise HTTPException(409, 'Forecast has no completed output to export')
        scored = next((s['result'] for s in detail['scores'] if s['result']['state'] == 'scored'), {})
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(['forecast_id', 'symbol', 'variant', 'mode', 'issued_at', 'prospective_eligible',
            'feed', 'cutoff', 'target_date', 'point_usd', 'q10_usd', 'q90_usd', 'flat_usd', 'drift_usd', 'observed_usd'])
        for case, prediction in zip(saved['cases'], saved['runtime']['results']):
            actual = case['actual'] or scored.get('actual')
            for i, day in enumerate(case['target_dates']):
                writer.writerow([identifier, saved['symbol'], case.get('variant', saved['request']['inputs']),
                    saved['mode'], saved['issued_at'], saved['prospective_eligible'], saved['feed'], case['cutoff'],
                    day, prediction['forecast'][i], prediction['quantiles'][i][0], prediction['quantiles'][i][8],
                    case['baseline'][i], case['drift_baseline'][i], actual[i] if actual else ''])
        return stream.getvalue()

    def export_evidence(self, identifier):
        detail = self.detail(identifier)
        # Only retained research receipts are included; never weights or provider settings.
        reference_keys = {'input_hash', 'result_hash', 'prediction_hash', 'artifact_hash',
                          'source_hash', 'forecast_hash', 'response_sha256'}
        pending, seen = [], set()
        def references(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in reference_keys and isinstance(item, str):
                        pending.append(item)
                    else:
                        references(item)
            elif isinstance(value, list):
                for item in value: references(item)
        references(detail)
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('forecast.json', json.dumps(detail, indent=2, allow_nan=False))
            if detail['result']:
                archive.writestr('predictions.csv', self.export_csv(identifier))
            while pending:
                digest = pending.pop()
                if digest in seen:
                    continue
                seen.add(digest)
                raw = self.store.get(digest)
                archive.writestr('objects/'+digest, raw)
                try: references(json.loads(raw))
                except (ValueError, UnicodeError): pass
            archive.writestr('README.txt', 'Local research evidence. objects/ filenames are SHA-256 hashes of their contents.\n'
                'Pending observations are blank in CSV. Model quantiles are uncalibrated.\n'
                'This archive contains numerical research and source receipts, not model weights or trading authority.\n')
        return stream.getvalue()

    def close(self):
        self.closing.set()
        self.outcome_worker['state'] = 'stopped'
        with self.lock:
            if self.process and self.process.poll() is None:
                self.process.terminate()
        self.recover()


def create_forecast_router(sessions, resolver, app):
    lab = ForecastLab(sessions, resolver)
    app.state.forecast_lab = lab
    on_lifecycle(app, 'startup')(lab.recover)
    on_lifecycle(app, 'shutdown')(lab.close)
    stop = asyncio.Event()
    task = None

    @on_lifecycle(app, 'startup')
    async def start_outcomes():
        nonlocal task
        async def loop():
            while not stop.is_set():
                await asyncio.to_thread(lab.score_due)
                try: await asyncio.wait_for(stop.wait(), timeout=60)
                except asyncio.TimeoutError: pass
        task = asyncio.create_task(loop())

    @on_lifecycle(app, 'shutdown')
    async def stop_outcomes():
        stop.set()
        if task:
            task.cancel()
            try: await task
            except asyncio.CancelledError: pass
    router = APIRouter(prefix='/api/discover/forecast', tags=['forecast'])

    @router.get('/status')
    def status():
        return {**lab.runtime(), 'jobs': lab.rows(),
                'outcome_worker': {**lab.outcome_worker, 'enabled': lab.auto_score_enabled()}}

    @router.post('/outcome-settings')
    def settings(request: OutcomeSettings):
        return lab.set_auto_score(request.enabled)

    @router.post('/jobs', status_code=202)
    def create(request: ForecastRequest):
        return lab.submit(request)

    @router.get('/jobs/{identifier}')
    def detail(identifier: str):
        return lab.detail(identifier)

    @router.get('/jobs/{identifier}/export.csv')
    def export_csv(identifier: str):
        contents = lab.export_csv(identifier)
        return Response(contents, media_type='text/csv', headers={
            'Content-Disposition': f'attachment; filename="{lab.get(identifier)["id"]}.csv"'})

    @router.get('/jobs/{identifier}/evidence.zip')
    def export_evidence(identifier: str):
        contents = lab.export_evidence(identifier)
        return Response(contents, media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="{lab.get(identifier)["id"]}-evidence.zip"'})

    @router.post('/jobs/{identifier}/score')
    def score(identifier: str):
        try:
            return lab.score(identifier)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    return router
