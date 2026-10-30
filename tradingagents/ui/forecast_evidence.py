"""Small, dated model-output source for explicitly requested Astra briefs."""
from datetime import datetime, timedelta
import json
from sqlmodel import select

from tradingagents.ui.forecast_lab import ForecastJob, ForecastLab
from tradingagents.ui.models import now_utc
from tradingagents.ui.evidence_review import price_indicators


def saved_forecast_source(sessions, symbol, *, root=None, now=None):
    now = now or now_utc()
    with sessions() as s:
        row = s.exec(select(ForecastJob).where(ForecastJob.state == 'completed',
            ForecastJob.request['symbol'].as_string() == symbol,
            ForecastJob.request['mode'].as_string() == 'prospective')
            .order_by(ForecastJob.created_at.desc()).limit(1)).first()
    if not row:
        return None, 'No saved forward model forecast was available; briefing did not start one.'
    try:
        detail = ForecastLab(sessions, None, root).detail(row.id)
        result = detail['result']
        issued = datetime.fromisoformat(result['issued_at'])
        if issued.tzinfo is None or not now-timedelta(days=7) <= issued <= now:
            return None, 'The saved model forecast is stale or has an invalid issue time; it was excluded.'
        if result['symbol'] != symbol or result['mode'] != 'prospective':
            raise ValueError('Forecast identity mismatch')
        outcome = next((s['result'] for s in detail['scores'] if s['result']['state'] == 'scored'), None)
        case = result['cases'][0]
        facts = {'symbol': symbol, 'forecast_id': row.id, 'result_sha256': row.result_hash,
            'model_id': result['model']['model_id'], 'model_revision': result['model']['revision'],
            'issued_at': result['issued_at'], 'input_cutoff': case['cutoff'],
            'target_dates': case['target_dates'], 'feed': result['feed'], 'price_basis': 'split-adjusted USD close',
            'prospective_eligible': result['prospective_eligible'],
            'outcomes': 'scored' if outcome else 'not_scored', 'variants': []}
        for item, prediction in zip(result['cases'], result['runtime']['results']):
            facts['variants'].append({'inputs': item.get('variant', row.request['inputs']),
                'final_session_point_usd': prediction['forecast'][-1],
                'final_session_q10_usd': prediction['quantiles'][-1][0],
                'final_session_q90_usd': prediction['quantiles'][-1][8], 'flat_baseline_usd': item['baseline'][-1]})
        if outcome:
            facts['observed_comparison'] = outcome.get('comparison', [])
        text = 'Experimental model output, not an observed market outcome or a trading recommendation. Quantile bands are uncalibrated.\n'+json.dumps(facts, ensure_ascii=True)
        source = {'source_id': 'forecast_lab', 'title': f'{symbol} saved TimesFM-3 research forecast',
            'publisher': 'Local Forecast Lab / Google TimesFM-3', 'kind': 'model_forecast',
            'published_at': result['issued_at'], 'retrieved_at': now.isoformat(), 'url': None, 'text': text,
            'origin': row.result_hash, 'data_as_of': case['cutoff']}
        if 'values' in case and 'dates' in case:
            indicators = price_indicators(case)
            source['price_context'] = {'source_id': 'price_context', 'title': f'{symbol} indicators from saved price history',
                'publisher': 'Alpaca saved closes / local calculations', 'kind': 'price_indicators',
                'published_at': None, 'retrieved_at': result['issued_at'], 'url': None,
                'origin': row.result_hash, 'data_as_of': case['cutoff'], 'indicators': indicators,
                'text': json.dumps({'forecast_id': row.id, 'result_sha256': row.result_hash, **indicators}, ensure_ascii=True)}
        return source, (
            'Forecast accuracy remains unvalidated until outcomes mature; model prices are not observed future prices.' if not outcome else
            'This scored forecast is a small research observation, not proof of investment edge.')
    except (ValueError, KeyError, IndexError, TypeError, OSError):
        return None, 'Saved forecast evidence could not be verified and was excluded from this brief.'
