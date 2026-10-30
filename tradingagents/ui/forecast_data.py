"""Dated market inputs and chronological evaluation for the local Forecast Lab."""
from datetime import date, datetime, time, timedelta, timezone
import math
from zoneinfo import ZoneInfo

NY = ZoneInfo('America/New_York')
CONTEXT = 256


def capture(provider, store, symbol, start, end, feed, with_market, now):
    """GET-only capture. Persist request and response bytes, including every page."""
    symbols = sorted({symbol, 'SPY'} if with_market else {symbol})
    receipts = []

    def get(url, params):
        response = provider._http_client.get(url, headers=provider._headers(),
            params=params, timeout=15, allow_redirects=False)
        if response.status_code != 200:
            raise ValueError(f'Alpaca returned HTTP {response.status_code}; check the configured data connection and feed entitlement')
        payload = response.json()
        raw = getattr(response, 'content', None)
        digest = store.put(raw) if isinstance(raw, bytes) else store.put_json(payload)
        receipts.append({'url': url, 'params': dict(params), 'response_sha256': digest,
                         'observed_at': datetime.now(timezone.utc).isoformat()})
        return payload

    calendar = get('https://paper-api.alpaca.markets/v2/calendar',
                   {'start': start.isoformat(), 'end': (end+timedelta(days=65)).isoformat()})
    if not isinstance(calendar, list) or not calendar:
        raise ValueError('Exchange calendar unavailable')
    try:
        for session in calendar:
            day = date.fromisoformat(session['date'])
            opens, closes = time.fromisoformat(session['open']), time.fromisoformat(session['close'])
            if opens.tzinfo or closes.tzinfo or opens >= closes or not start <= day <= end+timedelta(days=65):
                raise ValueError('Invalid exchange session')
        sessions = sorted(calendar, key=lambda r: r['date'])
    except (ValueError, KeyError, TypeError) as exc:
        raise ValueError('Invalid exchange calendar response') from exc
    dates = [r['date'] for r in sessions]
    if len(dates) != len(set(dates)):
        raise ValueError('Duplicate exchange sessions')
    params = {'symbols': ','.join(symbols), 'start': start.isoformat(),
              'end': datetime.combine(end+timedelta(days=1), time.min, NY).astimezone(timezone.utc).isoformat(),
              'timeframe': '1Day', 'adjustment': 'split', 'asof': '-', 'currency': 'USD',
              'feed': feed, 'sort': 'asc', 'limit': 10000}
    bars = {s: [] for s in symbols}
    seen_tokens = set()
    for _ in range(10):
        payload = get('https://data.alpaca.markets/v2/stocks/bars', params)
        for ticker in symbols:
            bars[ticker].extend((payload.get('bars') or {}).get(ticker, []))
        token = payload.get('next_page_token')
        if not token:
            break
        if token in seen_tokens:
            raise ValueError('Repeated market-data page token')
        seen_tokens.add(token)
        params['page_token'] = token
    else:
        raise ValueError('Market history exceeded the capture page limit')
    normalized = {}
    for ticker, rows in bars.items():
        normalized[ticker] = {}
        for row in rows:
            stamp = datetime.fromisoformat(row['t'].replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Undated market bar')
            day = stamp.astimezone(NY).date().isoformat()
            if day > end.isoformat():
                continue  # Inclusive provider endpoints can include the next midnight.
            close, volume = row.get('c'), row.get('v')
            if (isinstance(close, bool) or not isinstance(close, (float, int)) or
                    not math.isfinite(close) or close <= 0 or isinstance(volume, bool) or
                    not isinstance(volume, (float, int)) or not math.isfinite(volume) or volume < 0):
                raise ValueError('Invalid price or volume in source data')
            if day in normalized[ticker] or day not in dates:
                raise ValueError('Duplicate or non-session bar')
            normalized[ticker][day] = {'close': float(close), 'volume': float(volume)}
    return {'symbol': symbol, 'capture_started_at': now.isoformat(),
            'observed_at': receipts[-1]['observed_at'], 'start': start.isoformat(),
            'end': end.isoformat(), 'feed': feed, 'adjustment': 'split', 'currency': 'USD',
            'calendar': sessions, 'bars': normalized, 'receipts': receipts}


def make_cases(data, horizon, mode, with_market):
    dates = [r['date'] for r in data['calendar'] if r['date'] <= data['end']]
    if len(dates) < CONTEXT + (60 if mode == 'development' else 0):
        raise ValueError('Insufficient exchange sessions for 256 days of context')
    cuts = [len(dates)-60, len(dates)-40, len(dates)-20] if mode == 'development' else [len(dates)]
    full_dates = [r['date'] for r in data['calendar']]
    cases = []
    for cut in cuts:
        history = dates[cut-CONTEXT:cut]
        targets = full_dates[full_dates.index(history[-1])+1:][:horizon]
        if len(targets) != horizon:
            raise ValueError('Forecast horizon has incomplete exchange calendar coverage')
        try:
            values = [data['bars'][data['symbol']][d]['close'] for d in history]
            cov = [[data['bars']['SPY'][d]['close'] for d in history],
                   [data['bars'][data['symbol']][d]['volume'] for d in history]] if with_market else None
            actual = [data['bars'][data['symbol']][d]['close'] for d in targets] if mode == 'development' else None
        except KeyError as exc:
            raise ValueError(f'Missing required daily bar: {exc.args[0]}; no gap filling is permitted') from exc
        last = values[-1]
        drift = (last-values[0])/(len(values)-1)
        cases.append({'variant': 'market_volume' if with_market else 'stock',
                      'cutoff': history[-1], 'dates': history, 'values': values,
                      'covariates': cov, 'target_dates': targets, 'actual': actual,
                      'baseline': [last]*horizon,
                      'drift_baseline': [max(0, last+drift*(i+1)) for i in range(horizon)]})
    return cases


def experiment_cases(data, horizon, mode, inputs):
    """Paired variants share one capture, context, cutoffs and outcome calendar."""
    if inputs == 'compare':
        return make_cases(data, horizon, mode, False) + make_cases(data, horizon, mode, True)
    return make_cases(data, horizon, mode, inputs == 'market_volume')


def comparison_summary(cases, scores):
    if len(cases) != len(scores):
        raise ValueError('Every evaluation window needs a score')
    grouped = {}
    for case, score in zip(cases, scores):
        variant = case.get('variant', 'market_volume' if case.get('covariates') else 'stock')
        grouped.setdefault(variant, []).append(score)
    summary = []
    for variant, rows in grouped.items():
        n = sum(r['observations'] for r in rows)
        if not n:
            raise ValueError('Cannot summarize empty observations')
        weighted = {key: sum(r[key]*r['observations'] for r in rows)/n
                    for key in ['mae_usd', 'baseline_mae_usd', 'drift_mae_usd', 'interval_coverage_pct',
                                'mean_interval_width_usd', 'interval_score_usd']}
        base = weighted['baseline_mae_usd']
        summary.append({'variant': variant, 'windows': len(rows), 'observations': n, **weighted,
                        'windows_beating_flat': sum(r['mae_usd'] < r['baseline_mae_usd'] for r in rows),
                        'mae_reduction_pct': (1-weighted['mae_usd']/base)*100 if base > 0 else None})
    return summary


def validate_output(output, horizon, count):
    if len(output['results']) != count:
        raise ValueError('Model result count differs from the input')
    for result in output['results']:
        if len(result['forecast']) != horizon or len(result['quantiles']) != horizon:
            raise ValueError('Model horizon mismatch')
        for value in result['forecast']:
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid point forecast')
        for quantiles in result['quantiles']:
            if len(quantiles) != 9 or any(not math.isfinite(v) or v < 0 for v in quantiles) or quantiles != sorted(quantiles):
                raise ValueError('Invalid or crossing quantiles')


def metrics(case, result, actual):
    if len(actual) != len(case['target_dates']) or any(not math.isfinite(v) or v <= 0 for v in actual):
        raise ValueError('Scoring requires every target outcome')
    def mae(pred):
        return sum(abs(a-p) for a,p in zip(actual,pred))/len(actual)
    widths = [q[8]-q[0] for q in result['quantiles']]
    interval_scores = [q[8]-q[0]+10*max(q[0]-a, 0)+10*max(a-q[8], 0)
                       for a,q in zip(actual,result['quantiles'])]
    return {'mae_usd': mae(result['forecast']), 'baseline_mae_usd': mae(case['baseline']),
            'drift_mae_usd': mae(case['drift_baseline']),
            'interval_coverage_pct': 100*sum(q[0] <= a <= q[8] for a,q in zip(actual,result['quantiles']))/len(actual),
            'mean_interval_width_usd': sum(widths)/len(actual),
            'interval_score_usd': sum(interval_scores)/len(actual),
            'observations': len(actual)}


def score_saved(saved, fresh, now):
    case = saved['cases'][0]
    target_sessions = {s['date']: s for s in saved['calendar']}
    last_day = case['target_dates'][-1]
    # Daily aggregates are treated as final only after the entire NY date has ended.
    if now.astimezone(NY).date().isoformat() <= last_day:
        return {'state': 'pending', 'reason': 'The forecast horizon has not finished'}
    bars = fresh['bars'].get(saved['symbol'], {})
    for day, original in zip(case['dates'], case['values']):
        if day not in bars or not math.isclose(bars[day]['close'], original, rel_tol=1e-6, abs_tol=1e-5):
            return {'state': 'basis_changed', 'reason': 'Historical prices were revised or split-adjusted again; the original forecast is preserved and cannot be compared on this changed price basis'}
    if any(d not in bars or d not in target_sessions for d in case['target_dates']):
        return {'state': 'pending', 'reason': 'One or more target bars are unavailable'}
    actual = [bars[d]['close'] for d in case['target_dates']]
    # Forward paired cases must have the same target dates and observed context.
    scores = []
    for item, prediction in zip(saved['cases'], saved['runtime']['results']):
        if item['dates'] != case['dates'] or item['values'] != case['values'] or item['target_dates'] != case['target_dates']:
            raise ValueError('Forward comparisons do not share the same context and targets')
        scores.append(metrics(item, prediction, actual))
    if len(scores) != len(saved['cases']):
        raise ValueError('Incomplete saved model output')
    return {'state': 'scored', 'actual': actual, **scores[0], 'case_metrics': scores,
            'comparison': comparison_summary(saved['cases'], scores)}
