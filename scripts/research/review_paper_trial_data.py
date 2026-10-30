"""Audit preserved source captures without admitting data or calculating returns."""
import json
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from tradingagents.research.data.alpaca_capture import read_capture
from tradingagents.research.data.alpaca_reference import read_reference_capture, _reference_records
from tradingagents.research.data.store import ArtifactStore


def action_window_review(original, expanded, start, end):
    """Compare preserved events by effective date, never by payment-date proxy."""
    result={'window_start':start,'window_end':end,'effective_window_complete':False,
        'missing_from_original':[],'revised_source_ids':[],'removed_source_ids':sorted(set(original)-set(expanded)),
        'before_window':[],'after_window':[],'unclassified':[],'in_window_source_ids':[]}
    for identifier,entry in sorted(expanded.items()):
        record=entry['record']
        day=record.get('ex_date') or record.get('effective_date')
        # Capture decoding retains exact Decimal values; use decimal strings in
        # the review artifact, with the original response hash retained separately.
        def wire(value):
            if isinstance(value,Decimal): return str(value)
            raise TypeError(f'Unsupported source value: {type(value).__name__}')
        item={'source_id':identifier,'category':entry['category'],'record':json.loads(json.dumps(record,default=wire))}
        if identifier in original and original[identifier]!=entry:
            result['revised_source_ids'].append(identifier)
        try:
            # Strict ISO dates keep lexical comparisons meaningful.
            if not isinstance(day,str) or datetime.strptime(day,'%Y-%m-%d').strftime('%Y-%m-%d')!=day:
                raise ValueError('missing_or_invalid_effective_date')
        except ValueError:
            result['unclassified'].append(item);continue
        if day<start: result['before_window'].append(item)
        elif day>end: result['after_window'].append(item)
        else:
            result['in_window_source_ids'].append(identifier)
            if identifier not in original: result['missing_from_original'].append(item)
    result['status']='known_effective_window_omissions' if result['missing_from_original'] else 'no_omission_found_in_comparison'
    result['limitations']=['A completed process-date request does not establish complete effective-date coverage.',
        'Widening the interval can recover known events but cannot prove that the provider has published every event.',
        'Revisions, removed events, and unknown effective dates need review; originals are not overwritten.',
        'Actual retrieval times remain unchanged; no historical availability is inferred.']
    return result


def build_review(root=Path('.research-artifacts/paper-trial')):
    root=Path(root);store=ArtifactStore(root/'objects')
    index=json.loads((root/'research-capture-index.json').read_text())
    sip=json.loads((root/'sip-capture-review.json').read_text())
    criteria=store.json(index['criteria_hash'])
    calendar=read_reference_capture(store,index['captures']['calendar']['hash'])
    assert calendar.status=='complete'
    sessions=set(_reference_records(store,calendar)[0])
    feeds={};bars_by_feed={}
    for name,digest in [('iex',index['captures']['bars']['hash']),('sip',sip['hash'])]:
        receipt=read_capture(store,digest)
        assert receipt.status=='complete' and receipt.request.feed==name
        assert set(receipt.request.symbols)==set(criteria['symbols'])
        rows={};available=[]
        for page in receipt.pages:
            assert page.accepted
            for symbol,values in store.json(page.response_artifact)['bars'].items():
                for row in values:
                    day=datetime.fromisoformat(row['t'].replace('Z','+00:00')).astimezone(ZoneInfo('America/New_York')).date().isoformat()
                    key=(symbol,day)
                    if key in rows:assert rows[key]==row
                    rows[key]=row
            available.append(page.processed_at)
        coverage={}
        for symbol in criteria['symbols']:
            days={day for sym,day in rows if sym==symbol}
            coverage[symbol]={'bars':len(days),'missing_sessions':sorted(sessions-days),'non_session_dates':sorted(days-sessions)}
        feeds[name]={'capture_hash':digest,'coverage':coverage,
            'observed_available_from':min(available).isoformat(),'observed_available_through':max(available).isoformat(),
            'source_rows':len(rows),'historical_first_publication_times_present':False}
        bars_by_feed[name]=rows
    assert bars_by_feed['iex'].keys()==bars_by_feed['sip'].keys()
    differences={field:sum(left[field]!=bars_by_feed['sip'][key][field] for key,left in bars_by_feed['iex'].items())
        for field in ['o','h','l','c','v']}
    actions=read_reference_capture(store,index['captures']['corporate_actions']['hash'])
    assert actions.status=='complete'
    action_rows,origins=_reference_records(store,actions)
    boundary_review=None
    expanded_index=root/'actions-expanded-capture.json'
    if expanded_index.exists():
        expanded_info=json.loads(expanded_index.read_text())
        expanded=read_reference_capture(store,expanded_info['capture_hash'])
        if expanded.status!='complete' or expanded.request.kind!='corporate_actions':
            raise ValueError('Expanded corporate-action capture is incomplete')
        if expanded.request.symbols!=actions.request.symbols or expanded.request.start>actions.request.start or expanded.request.end<actions.request.end:
            raise ValueError('Expanded corporate-action capture does not cover the original request')
        expanded_rows,_=_reference_records(store,expanded)
        boundary_review=action_window_review(action_rows,expanded_rows,criteria['warmup'][0],criteria['historical_holdout'][1])
        boundary_review.update(original_capture_hash=index['captures']['corporate_actions']['hash'],
            expanded_capture_hash=expanded_info['capture_hash'],intent_hash=expanded_info['intent_hash'],
            expanded_received_at=expanded.completed_at.isoformat())
    dividends=[x['record'] for x in action_rows.values() if x['category']=='cash_dividends']
    assets={symbol:{'asset_id':row['asset_id'],'exchange':row['exchange'],
        'observed_at':store.json(row['hash'])['observed_at'],'historical_effective_dates_present':False}
        for symbol,row in index['assets'].items()}
    windows={}
    for key in ['development','validation','historical_holdout']:
        end=datetime.fromisoformat(criteria[key][1]+'T23:59:59').replace(tzinfo=ZoneInfo('America/New_York'))
        windows[key]={'end':end.isoformat(),'all_captures_received_after_window':
            all(datetime.fromisoformat(feed['observed_available_from'])>end for feed in feeds.values())}
    review={'schema_version':'paper_trial_data_readiness_v1','reviewed_at':datetime.now(timezone.utc).isoformat(),
        'criteria_hash':index['criteria_hash'],'sip_selection_intent_hash':sip['intent_hash'],
        'calendar_hash':index['captures']['calendar']['hash'],'calendar_sessions':len(sessions),
        'feeds':feeds,'cross_feed_changed_bar_fields':differences,
        'corporate_actions':{'capture_hash':index['captures']['corporate_actions']['hash'],
            'categories':dict(Counter(x['category'] for x in action_rows.values())),
            'dividends_missing_currency':sum('currency' not in x for x in dividends),
            'ordinary_domestic_dividends':sum(x.get('foreign') is False and x.get('special') is False for x in dividends),
            'actual_available_from':min(x.processed_at for x in origins.values()).isoformat()},
        'current_assets':assets,'historical_windows':windows,
        'action_effective_window_review':boundary_review,
        'source_documentation':{'url':'https://docs.alpaca.markets/us/docs/market-data-faq',
            'interpretation':'Historical SIP access is available for sufficiently old requests. Daily bar timestamps identify New York date buckets, not publication times. Daily OHLC follows eligible-trade conditions; volume may include extended-hours trades. These bars do not establish official auction fills.'},
        'readiness':'source_capture_complete_research_admission_incomplete','snapshot_admitted':False,
        'performance_evaluated':False,
        'remaining':['Historical availability and revision assumptions must be explicit; current receipt times cannot be backdated.',
            'Processing-date request bounds do not guarantee effective-date event coverage; review expanded-capture omissions and carry-in/carry-out events.',
            'Effective-dated historical instrument identity remains unverified.',
            'Dividend currency and payable-time interpretation remain undeclared; a date alone supplies no intraday payment timestamp.',
            'Retain the separately reviewed NUAN merger record and applicability conclusion; no unsupported-row override has been applied.',
            'Next-session daily open is an eligible-trade simulation proxy, not an official opening-auction or broker execution guarantee.',
            'Review the proposal before freezing its rules; paper-order approval is separate.']}
    return review


def main():
    root=Path('.research-artifacts/paper-trial');store=ArtifactStore(root/'objects')
    review=build_review(root)
    feeds=review['feeds']
    differences=review['cross_feed_changed_bar_fields'];boundary_review=review['action_effective_window_review']
    windows=review['historical_windows']
    digest=store.put_json(review)
    (root/'data-readiness-review.json').write_text(json.dumps({'hash':digest,'review':review},indent=2)+'\n')
    print(json.dumps({'hash':digest,'sessions':review['calendar_sessions'],'bars_per_feed':{k:v['source_rows'] for k,v in feeds.items()},
        'cross_feed_changed_fields':differences,'dividends_missing_currency':review['corporate_actions']['dividends_missing_currency'],
        'known_missing_effective_window_events':len(boundary_review['missing_from_original']) if boundary_review else None,
        'historical_windows':windows,'readiness':review['readiness']},indent=2))


if __name__=='__main__':main()
