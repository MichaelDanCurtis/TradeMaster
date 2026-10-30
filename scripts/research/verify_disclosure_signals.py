"""Audit frozen disclosure selections, coverage and independent archive overlap."""
import argparse
import bisect
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import json
from pathlib import Path

from scripts.research.disclosure_signals import select, sha, write


def decimal_key(value):
    return str(Decimal(str(value)).normalize())


def run(root):
    lock = json.loads((root/'targets-lock.json').read_text())
    assert all(sha(root/name) == h for name, h in lock['files'].items())
    panel = json.loads((root/'panel.json').read_text()); dates = panel['dates']; names = panel['symbols']
    protocol = json.loads((root/'protocol.json').read_text()); checks = []; coverage = {}; used = set()
    for source in ['senate', 'insider_proxy']:
        events = json.loads((root/(source+'-events.json')).read_text())
        counts = Counter()
        for event in events:
            if not '2018-10-01' <= event['disclosed'] < '2026-01-01':
                continue
            t = bisect.bisect_right(dates, event['disclosed'])
            if event['symbol'] not in names:
                counts['outside_historical_union'] += 1
            elif not panel['membership'][t-1][names.index(event['symbol'])]:
                counts['not_member_at_disclosure'] += 1
            else:
                counts['member_at_disclosure'] += 1
        coverage[source] = dict(counts)
        for experiment in [e for e in protocol['experiments'] if e['source'] == source]:
            for delay in protocol['additional_session_delays']:
                rows = json.loads((root/(experiment['label']+f'-delay{delay}-targets.json')).read_text())
                for row in rows:
                    assert len(row['selected']) <= 10
                    assert abs(sum(row['target_weights'])+row['cash_weight']-1) < 1e-10
                    assert all(weight in (0., 0.1) for weight in row['target_weights'])
                    for ids in row['signal_ids'].values():
                        if source == 'insider_proxy':
                            used.update(ids)
                for index in sorted({0, len(rows)//2, len(rows)-1}):
                    row = rows[index]; t = row['entry_index']
                    members = [s for s, yes in zip(names, panel['membership'][t-1]) if yes]
                    retired = [e['old'] for e in panel['valuation_only_reconciliation']['events'] if e['date'] <= dates[t-1] and e['old'] not in [x['symbol'] for x in e['successors']]]
                    past = [e for e in events if e['disclosed'] < dates[t]]
                    replay = select(past, dates[:t+1], t, members, delay, retired)
                    assert all(replay[k] == row[k] for k in ['selected', 'scores', 'signal_ids'])
                    checks.append({'experiment': experiment['label'], 'delay': delay, 'date': row['date'], 'future_disclosures_removed': True, 'future_calendar_removed': True})
    # Corroboration, not admission: the second archive retains accessions but
    # omits filing dates and may share the same original SEC source.
    events = {e['id']: e for e in json.loads((root/'insider_proxy-events.json').read_text()) if e['id'] in used}
    keys = defaultdict(set)
    for identity, e in events.items():
        keys[(e['symbol'], str(int(e['buyer'])), e['transacted'], decimal_key(e['shares']), decimal_key(e['price']))].add(identity)
    matches = defaultdict(set)
    with (root/'sources/form4-transactions.csv').open() as stream:
        for row in csv.DictReader(stream):
            if row['transaction_code'] != 'P' or row['acquired_disposed'] != 'A' or row['form_type'] != '4.0':
                continue
            try:
                key = (row['ticker'], str(int(row['rptownercik'])), row['transaction_date'], decimal_key(row['shares']), decimal_key(row['price_per_share']))
            except (ValueError, ArithmeticError):
                continue
            for identity in keys.get(key, []):
                matches[identity].add(row['accession_number'])
    write(root/'source-crosscheck.json', {'selected_insider_signal_count': len(used), 'matching_nominal_form4_transactions': len(matches),
          'unmatched': sorted(used-set(matches)), 'matches': {k: sorted(v) for k, v in matches.items()},
          'source_sha256': sha(root/'sources/form4-transactions.csv'),
          'limitation': 'Independent archival transform corroborates transaction fields only. Not an independent economic source or verification of filing date, issuer identity, original vs amended document type, or completeness.'})
    repaired = json.loads((root/'dow-valuation/panel.json').read_text())
    for s in panel['series']:
        if s != 'DOW':
            assert panel['series'][s] == repaired['series'][s]
    assert all(v is None for d, v in zip(dates, repaired['series']['DOW']['open']) if d < '2019-04-02')
    write(root/'verification.json', {'frozen_hashes_verified': True, 'causal_replays': checks,
          'source_coverage': coverage, 'dow_only_change_verified': True,
          'cross_archive_matches': len(matches), 'selected_insider_signal_count': len(used),
          'limitations': ['No claims of complete original Form4-only or full congressional data.', 'Membership/price history is not an independently certified security master.']})
    print(json.dumps({'causal_replays': len(checks), 'cross_archive_matches': len(matches), 'selected_insider_signal_count': len(used)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument('--root', type=Path, required=True)
    run(parser.parse_args().root)
