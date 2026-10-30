"""Historical disclosure-signal research. Never connects to a broker.

Archive normalization is deliberately separate from selection and valuation.
Publication dates are date-only: the whole filing day must elapse before use.
"""
from __future__ import annotations

import argparse
import bisect
from collections import Counter, defaultdict
import copy
import csv
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
from html.parser import HTMLParser
import json
import math
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()


def day(value):
    if not value:
        raise ValueError('Missing date')
    if hasattr(value, 'date'):
        return value.date().isoformat()
    for fmt in ('%Y-%m-%d', '%m/%d/%Y', '%d-%b-%Y'):
        try:
            parsed = datetime.strptime(str(value), fmt).date()
            if not 1990 <= parsed.year <= 2026:
                raise ValueError('Date outside study bounds')
            return parsed.isoformat()
        except ValueError:
            pass
    raise ValueError('Invalid date')


def positive(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result <= 0:
            raise ValueError('Not positive and finite')
        return result
    except InvalidOperation as exc:
        raise ValueError('Invalid numeric field') from exc


def symbol(value):
    class TextOnly(HTMLParser):
        def __init__(self):
            super().__init__(); self.parts = []
        def handle_data(self, text):
            self.parts.append(text)
    parser = TextOnly(); parser.feed(str(value or ''))
    value = ''.join(parser.parts).strip().upper().replace('/', '.')
    if not re.fullmatch(r'[A-Z]{1,5}(?:\.[A-Z])?', value):
        raise ValueError('No unambiguous stock symbol')
    return value


def normalize_senate(reports):
    events, rejected, report_counts = [], Counter(), Counter()
    for report in reports:
        try:
            disclosed = day(report['date_recieved'])
        except (ValueError, KeyError):
            rejected['report_missing_disclosure_date'] += 1
            continue
        report_counts[disclosed[:7]] += 1
        for ordinal, row in enumerate(report['transactions']):
            if row.get('type') != 'Purchase':
                rejected['not_purchase'] += 1
                continue
            if row.get('asset_type') != 'Stock':
                rejected['not_explicit_stock'] += 1
                continue
            try:
                s = symbol(row['ticker'])
                transacted = day(row['transaction_date'])
                if transacted > disclosed:
                    raise ValueError('Transaction after disclosure')
                numbers = re.findall(r'\d[\d,]*', row['amount'])
                amount = positive(numbers[0].replace(',', ''))
                source_id = report['ptr_link']
                if not source_id.startswith('https://efdsearch.senate.gov/'):
                    raise ValueError('Missing source report')
            except (ValueError, KeyError, IndexError):
                rejected['invalid_purchase_fields'] += 1
                continue
            economic = [source_id, ordinal, row]
            events.append({'id': digest(economic), 'symbol': s, 'disclosed': disclosed,
                           'transacted': transacted, 'amount': str(amount),
                           'buyer': report.get('bioguide') or report['office'],
                           'source': source_id, 'source_row': ordinal,
                           'asset_description': row.get('asset_description', '')})
    return dedupe(events), {'rejected': dict(rejected), 'reports_by_month': dict(sorted(report_counts.items())),
                            'scope': 'Senate only; archived electronic PTRs, not all Congress. Scanned PDF gaps remain.'}


def dedupe(events):
    """Only exact source duplicates; later amendments cannot erase old events."""
    unique = {}
    for event in events:
        previous = unique.get(event['id'])
        if previous is not None and previous != event:
            raise ValueError('Conflicting source identity')
        unique[event['id']] = event
    return sorted(unique.values(), key=lambda e: (e['disclosed'], e['id']))


def normalize_insider(rows):
    """Provisional SEC-derived archive, not certified original Form 4 coverage.

The archive lacks accession/document type. Keep that limitation explicit; do
not invent either or call its normalized PURCHASE field verified open market.
"""
    events, rejected = [], Counter()
    for row in rows:
        if row['transaction_type'] != 'PURCHASE' or row['transaction_direction'] != 'ACQUIRED':
            rejected['not_purchase_acquisition'] += 1
            continue
        if row['security_class'] != 'NON_DERIVATIVE':
            rejected['derivative'] += 1
            continue
        roles = set(row['insider_role'] or [])
        if not roles.intersection({'OFFICER', 'DIRECTOR'}):
            rejected['not_director_or_officer'] += 1
            continue
        # Non-derivative preferred shares and debt are not the common equity.
        title = (row['security_title'] or '').lower()
        if not ('common' in title or 'ordinary' in title) or any(x in title for x in ['preferred', 'option', 'warrant', 'unit', 'convertible']):
            rejected['not_explicit_common_or_ordinary_stock'] += 1
            continue
        try:
            s = symbol(row['security_symbol'])
            disclosed, transacted = day(row['filing_date']), day(row['event_date'])
            if transacted > disclosed:
                raise ValueError('Future transaction')
            shares, price = positive(row['transaction_shares']), positive(row['transaction_price_per_share'])
            amount = shares * price
            buyer = str(int(row['cik']))
        except (ValueError, TypeError):
            rejected['invalid_purchase_fields'] += 1
            continue
        economic = [s, buyer, disclosed, transacted, str(shares), str(price), title,
                    row.get('ownership_type'), row.get('shares_after_transaction')]
        events.append({'id': digest(economic), 'symbol': s, 'disclosed': disclosed,
                       'transacted': transacted, 'amount': str(amount), 'buyer': buyer,
                       'shares': str(shares), 'price': str(price), 'asset_description': row.get('company_name', ''),
                       'source': 'OpenSECFinancials insider_transactions archive',
                       'qualification': 'Missing accession, issuer CIK and original/amended form type; proxy only'})
    return dedupe(events), {'rejected': dict(rejected), 'scope': 'SEC-derived Forms 3/4/5 archive proxy; original Form 4-only hypothesis remains unqualified.'}


def eligible_index(disclosed, dates, delay):
    if delay < 0:
        raise ValueError('Negative disclosure lag')
    return bisect.bisect_right(dates, disclosed) + delay


def select(events, dates, index, members, delay=0, retired=()):
    """No prices, realized returns or future membership enter this function."""
    lower = (date.fromisoformat(dates[index]) - timedelta(days=90)).isoformat()
    totals = defaultdict(Decimal)
    sources = defaultdict(list)
    members = set(members) - set(retired)
    for event in events:
        if lower <= event['disclosed'] < dates[index] and eligible_index(event['disclosed'], dates, delay) <= index and event['symbol'] in members:
            totals[event['symbol']] += positive(event['amount'])
            sources[event['symbol']].append(event['id'])
    selected = sorted(totals, key=lambda s: (-totals[s], s))[:10]
    return {'selected': selected, 'scores': {s: str(totals[s]) for s in sorted(totals)},
            'signal_ids': {s: sorted(sources[s]) for s in selected}}


def targets(panel, events, start, end, delay):
    dates, names = panel['dates'], panel['symbols']
    first, last = bisect.bisect_left(dates, start), bisect.bisect_left(dates, end)
    if first >= last or last >= len(dates):
        raise ValueError('No covered evaluation interval')
    rows, previous_week = [], None
    conversions = panel['valuation_only_reconciliation']['events']
    for t in range(first, last):
        week = date.fromisoformat(dates[t]).isocalendar()[:2]
        if week == previous_week:
            continue
        previous_week = week
        # Membership at the preceding close avoids same-open membership news.
        members = [s for s, active in zip(names, panel['membership'][t-1]) if active]
        retired = [e['old'] for e in conversions if e['date'] <= dates[t-1] and e['old'] not in [c['symbol'] for c in e['successors']]]
        selection = select(events, dates, t, members, delay, retired)
        weights = [0.1 if s in selection['selected'] else 0. for s in names] + [0.]
        rows.append({'date': dates[t], 'entry_index': t, 'exit_index': last,
                     'target_weights': weights, 'cash_weight': 1 - len(selection['selected'])/10,
                     **selection})
    return rows


def prepare(root):
    import pyarrow.parquet as pq
    sources = root/'sources'
    senate, senate_audit = normalize_senate(json.loads((sources/'senate-daily.json').read_text()))
    columns = ['transaction_type', 'transaction_direction', 'security_class', 'security_title',
               'security_symbol', 'insider_role', 'cik', 'filing_date', 'event_date',
               'transaction_shares', 'transaction_price_per_share', 'company_name',
               'ownership_type', 'shares_after_transaction']
    table = pq.read_table(sources/'open-insider.parquet', columns=columns,
                          filters=[('transaction_type', '=', 'PURCHASE')])
    pq.write_table(table, sources/'open-purchases.parquet')
    # Keep only analytical fields; the raw source remains preserved separately.
    insider, insider_audit = normalize_insider(table.to_pylist())
    for key, events, audit in [('senate', senate, senate_audit), ('insider_proxy', insider, insider_audit)]:
        write(root/(key+'-events.json'), events)
        audit.update(event_count=len(events), symbols=len({e['symbol'] for e in events}),
                     first_disclosure=min((e['disclosed'] for e in events), default=None), last_disclosure=max((e['disclosed'] for e in events), default=None),
                     events_by_year=dict(sorted(Counter(e['disclosed'][:4] for e in events).items())))
        write(root/(key+'-coverage.json'), audit)
    previous = Path('.research-artifacts/prediction-historical-validation-2026-09-07')
    early = json.loads((previous/'historical-early-event-panel.json').read_text())
    panel = json.loads((previous/'historical-late-event-panel.json').read_text())
    panel['successor_only_symbols'] = sorted(set(panel['successor_only_symbols'] + early['successor_only_symbols']))
    for s, series in early['series'].items():
        if s not in panel['series']:
            panel['series'][s] = {k: [None]*len(panel['dates']) for k in series}
        for field, values in series.items():
            for i, value in enumerate(values):
                old = panel['series'][s][field][i]
                if value is not None and old is not None and value != old:
                    raise ValueError('Historical source coordinates differ')
                if old is None:
                    panel['series'][s][field][i] = value
    panel['valuation_only_reconciliation']['events'] += early['valuation_only_reconciliation']['events']
    write(root/'panel.json', panel)
    # Date coverage, not outcomes, determines these windows. The archived
    # Senate feed ends March 10 2021: only 2019 and 2020 are full target years.
    experiments = [{'source': 'senate', 'label': 'senate-2019-2020', 'start': '2019-01-01', 'end': '2021-01-01'}]
    experiments += [{'source': 'senate', 'label': f'senate-{y}', 'start': f'{y}-01-01', 'end': f'{y+1}-01-01'} for y in [2019, 2020]]
    experiments += [{'source': 'insider_proxy', 'label': 'insider-proxy-2019-2025', 'start': '2019-01-01', 'end': '2026-01-01'}]
    experiments += [{'source': 'insider_proxy', 'label': f'insider-proxy-{y}', 'start': f'{y}-01-01', 'end': f'{y+1}-01-01'} for y in range(2019, 2026)]
    protocol = {'created_at': datetime.now(timezone.utc).isoformat(), 'intent_sha256': sha(root/'intent.json'),
                'experiments': experiments, 'cost_bps': [11, 22], 'additional_session_delays': [0, 5],
                'policy': 'Weekly first session open, prior90calendar-day disclosed purchase dollars, descending rank then ticker, ten10%slots with unused cash. Date-only disclosures available strictly next session. Membership at prior close. No price or outcome filtering.',
                'source_amendment': 'Direct SEC bulk download returned403. Archived normalized source lacks accession and document type. Run a separately named insider_proxy; do not claim original Form4-only test is qualified. Senate daily archive retains report disclosure date and link but scanned reports may be absent. No House or entire Congress coverage claim.',
                'accounting': 'Adjusted daily opens, fractional shares, zero cash interest, no leverage, 11/22bps all buys/sells including endpoint liquidation. Existing explicit merger entitlements; weekly cash availability is an unverified research assumption. Missing required mark blocks complete results.',
                'qualification': 'Exploratory archive diagnostics; historical membership/identities, amendments, signal completeness and corporate actions not fully qualified. Never proof of broker returns or a tradable edge.',
                'source_hashes': {str(p): sha(p) for p in [sources/'senate-daily.json', sources/'open-insider.parquet', sources/'open-purchases.parquet', previous/'historical-early-event-panel.json', previous/'historical-late-event-panel.json']}}
    write(root/'protocol.json', protocol)
    target_files = []
    for experiment in experiments:
        source_events = senate if experiment['source'] == 'senate' else insider
        for delay in protocol['additional_session_delays']:
            rows = targets(panel, source_events, experiment['start'], experiment['end'], delay)
            path = root/(experiment['label']+f'-delay{delay}-targets.json')
            write(path, rows); target_files.append(path)
    files = [root/'protocol.json', root/'panel.json', root/'senate-events.json', root/'insider_proxy-events.json'] + target_files
    write(root/'targets-lock.json', {'frozen_at': datetime.now(timezone.utc).isoformat(), 'files': {p.name: sha(p) for p in files}, 'code_sha256': sha(__file__)})
    print(json.dumps({'senate_events': len(senate), 'insider_proxy_events': len(insider), 'frozen_target_files': len(target_files)}), flush=True)


def score(root):
    from scripts.research.prediction_event_accounting import simulate_events
    from scripts.research.evaluate_astra_capsules import compare_recursive
    lock = json.loads((root/'targets-lock.json').read_text())
    if any(sha(root/name) != h for name, h in lock['files'].items()):
        raise ValueError('Frozen inputs changed')
    if sha(__file__) != lock['code_sha256']:
        raise ValueError('Frozen disclosure code changed')
    panel = json.loads((root/'panel.json').read_text())
    protocol = json.loads((root/'protocol.json').read_text())
    events = panel['valuation_only_reconciliation']['events']
    result = {}
    for experiment in protocol['experiments']:
        label = experiment['label']; result[label] = {}
        for delay in protocol['additional_session_delays']:
            rows = json.loads((root/f'{label}-delay{delay}-targets.json').read_text())
            for bps in protocol['cost_bps']:
                name = f'delay{delay}-cost{bps}'
                a = simulate_events(panel, rows, events, bps/10000)
                b = simulate_events(panel, rows, events, bps/10000, audit=True)
                compare_recursive(a, b)
                result[label][name] = a
                print(label, name, a['state'], a.get('cagr'), a.get('date'), a.get('unresolved_symbols'), flush=True)
        control = copy.deepcopy(rows[:1]); control[0]['target_weights'] = [0.]*len(panel['symbols'])+[1.]
        for bps in protocol['cost_bps']:
            a = simulate_events(panel, control, [], bps/10000)
            b = simulate_events(panel, control, [], bps/10000, audit=True)
            compare_recursive(a, b)
            result[label][f'SPY-cost{bps}'] = a
        write(root/'results.json', result)
    write(root/'scoring-verification.json', {'completed_at': datetime.now(timezone.utc).isoformat(),
                                           'cost_solver_replays': len(protocol['experiments'])*6,
                                           'scope': 'Two transaction-cost solvers; shared corporate-action processing.'})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'score'])
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    if args.stage == 'prepare':
        if (args.root/'targets-lock.json').exists():
            raise ValueError('Frozen study already exists; use a separately versioned root')
        prepare(args.root)
    else:
        score(args.root)


if __name__ == '__main__':
    main()
