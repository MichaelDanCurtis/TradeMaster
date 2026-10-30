"""Deterministic evidence inventory and indicators; no model or trading calls."""
from copy import deepcopy
from datetime import date, datetime, timezone
import math
import statistics

from tradingagents.research.contracts import content_hash


def price_indicators(case):
    """Use only saved context, never the forecast path or held-out outcomes."""
    values, dates = case['values'], case['dates']
    if len(values) != 256 or len(dates) != 256:
        raise ValueError('Expected a 256-session price context')
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v <= 0 for v in values):
        raise ValueError('Invalid price context')
    parsed = [date.fromisoformat(d) for d in dates]
    if any(a >= b for a, b in zip(parsed, parsed[1:])) or dates[-1] != case['cutoff']:
        raise ValueError('Price context dates do not match cutoff')
    returns = [math.log(b/a) for a, b in zip(values[-21:-1], values[-20:])]
    return {'cutoff': dates[-1], 'context_sessions': len(values), 'price_basis': 'split-adjusted USD close',
        'last_close_usd': values[-1], 'sma_20_usd': statistics.mean(values[-20:]),
        'sma_50_usd': statistics.mean(values[-50:]),
        'return_20_sessions_pct': (values[-1]/values[-21]-1)*100,
        'realized_volatility_20_pct': statistics.stdev(returns)*math.sqrt(252)*100,
        'method': 'SMA: arithmetic mean of closes. Return: close / close 20 sessions earlier - 1. '
                  'Volatility: sample standard deviation of 20 log returns, annualized with sqrt(252). '
                  'Dividends are not reinvested; these are historical calculations, not forecasts.'}


def freeze_review_packet(packet, *, now=None):
    """Record age at collection without calling an old source current or independent."""
    now = now or datetime.now(timezone.utc)
    packet = deepcopy(packet)
    manifest, retained, seen = [], [], set()
    for source in packet['sources']:
        identifier = source['source_id']
        if identifier in seen:
            raise ValueError('Duplicate evidence source identifier')
        seen.add(identifier)
        dates, invalid = {}, False
        for field in ('published_at', 'retrieved_at'):
            value = source.get(field)
            try:
                if value is None:
                    dates[field] = {'precision': 'unknown', 'age_hours': None}
                elif len(value) == 10:
                    if date.fromisoformat(value) > now.date():
                        raise ValueError('Future date')
                    dates[field] = {'precision': 'date_only', 'age_hours': None}
                else:
                    stamp = datetime.fromisoformat(value)
                    if stamp.tzinfo is None or stamp > now:
                        raise ValueError('Invalid timestamp')
                    dates[field] = {'precision': 'timestamp', 'age_hours': round((now-stamp).total_seconds()/3600, 2)}
            except (ValueError, TypeError):
                invalid = True
        if invalid:
            packet['gaps'].append(f'{identifier} was excluded because its dates could not be verified.')
            continue
        retained.append(source)
        manifest.append({'source_id': identifier, 'kind': source.get('kind', 'unknown'),
            'sha256': content_hash(source), 'published': dates['published_at'],
            'retrieved': dates['retrieved_at'], 'data_as_of': source.get('data_as_of'),
            'origin': source.get('origin', identifier)})
    packet['sources'] = retained
    kinds = {s.get('kind') for s in retained}
    categories = {'Market quote': {'quote'}, 'Company news': {'news'},
        'Company facts or filings': {'company_snapshot', 'filing_excerpt', 'historical_facts'},
        'Historical price indicators': {'price_indicators'}, 'Saved model forecast': {'model_forecast'},
        'Selected images / PDF pages': {'chart_image', 'pdf_page'}}
    packet['review'] = {'version': 2, 'frozen_at': now.isoformat(), 'sources': manifest,
        'coverage': [{'category': label, 'present': bool(kinds & accepted)} for label, accepted in categories.items()],
        'limitations': [
            'Source ages are measured when this packet was frozen, not when you view it.',
            'Retrieved time records local collection, not proof of when the information first became public.',
            'A chart, an indicator and a model forecast derived from the same prices are not independent evidence.',
            'This is a present-day evidence review, not a historical point-in-time backtest.',
            'No combined confidence probability or feature attribution is calculated.']}
    return packet
