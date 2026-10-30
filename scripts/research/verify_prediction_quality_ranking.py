"""Audit the declared pre-evaluation structural-event quarantine sensitivity."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research.verify_prediction_wide_ranking import audit, eligible_at, require, sha, valid


EVENTS = [('APTV', '2017-12-05'), ('RTX', '2020-04-03'), ('EQT', '2018-11-13')]


def verify_derivation(root, universe):
    source_path = root / f'panel-{universe}.json'
    target_path = root / f'panel-{universe}-quality.json'
    source = json.loads(source_path.read_text())
    target = json.loads(target_path.read_text())
    for key in source:
        if key != 'series':
            require(source[key] == target[key], f'Original panel field changed: {key}')
    require(set(target) - set(source) == {'data_quality_quarantine'}, 'Unexpected added panel fields')
    require(set(source['series']) == set(target['series']), 'Series universe changed')
    receipts = json.loads((root / 'quality-receipt.json').read_text())
    receipt = next(r for r in receipts if r['universe'] == universe)
    require(receipt['original_panel_sha256'] == sha(source_path) and receipt['derived_panel_sha256'] == sha(target_path), 'Quarantine derivation receipt mismatch')
    protocol = json.loads((root / 'quality-protocol.json').read_text())
    require([(r['symbol'], r['date']) for r in protocol['events']] == EVENTS, 'Declared event list differs')
    applicable = [(s, d, source['dates'].index(d)) for s, d in EVENTS if s in source['symbols']]
    require([(r['symbol'], r['date']) for r in receipt['applied']] == [(s, d) for s, d, _ in applicable], 'Applied receipt events differ')
    event_indices = {s: i for s, _, i in applicable}
    changed = {s: {'close': 0, 'open': 0} for s in event_indices}
    total_compared = 0
    for symbol, fields in source['series'].items():
        require(set(fields) == set(target['series'][symbol]), 'Source field set changed')
        event = event_indices.get(symbol)
        for field, before in fields.items():
            after = target['series'][symbol][field]
            require(len(before) == len(after), 'Array length changed')
            for i, (old, new) in enumerate(zip(before, after)):
                quarantine = event is not None and ((field == 'close' and i == event) or (field == 'open' and event - 21 <= i <= event + 21))
                expected = None if quarantine else old
                require(new == expected, f'Unexpected mutation: {symbol}/{field}/{source["dates"][i]}')
                if old != new:
                    changed[symbol][field] += 1
                total_compared += 1
    primary_predictions = json.loads((root / universe / 'ranking/predictions.json').read_text())
    quality_predictions = json.loads((root / f'{universe}-quality' / 'ranking/predictions.json').read_text())
    require(primary_predictions['metadata']['runner_sha256'] == quality_predictions['metadata']['runner_sha256'], 'Ranking implementation changed')
    require(primary_predictions['metadata']['frozen_primitives_sha256'] == quality_predictions['metadata']['frozen_primitives_sha256'], 'Frozen models changed')
    for key, value in primary_predictions['metadata'].items():
        if key != 'panel_sha256':
            require(value == quality_predictions['metadata'][key], f'Ranking metadata changed: {key}')
    require(len(primary_predictions['rows']) == len(quality_predictions['rows']), 'Evaluation origin count changed')
    for a, b in zip(primary_predictions['rows'], quality_predictions['rows']):
        for key in ('origin_index', 'date', 'entry_index', 'exit_index', 'truncated', 'eligible_symbols'):
            require(a[key] == b[key], f'Evaluation schedule or eligibility changed: {key}')
    primary_outcomes = json.loads((root / universe / 'ranking/outcomes.json').read_text())['outcomes']
    quality_outcomes = json.loads((root / f'{universe}-quality' / 'ranking/outcomes.json').read_text())['outcomes']
    require(primary_outcomes == quality_outcomes, 'Evaluation outcome values changed')
    training_origins = [r['origin_index'] for r in quality_predictions['training_coverage']]
    exclusions = []
    for symbol, day, event in applicable:
        j = source['symbols'].index(symbol)
        crossing = [o for o in training_origins if o + 1 <= event <= o + 22]
        require(crossing, 'No training label spans declared event')
        for o in crossing:
            require(not (valid(target['series'][symbol]['open'][o + 1]) and valid(target['series'][symbol]['open'][o + 22])), 'Event-crossing label survived quarantine')
        affected_lookbacks = [o for o in training_origins if event <= o <= event + 252]
        for o in affected_lookbacks:
            indices, _ = eligible_at(target, o)
            require(j not in indices, 'Quarantined historical close survived feature eligibility')
        exclusions.append({'symbol': symbol, 'event_date': day,
                           'changed_close_cells': changed[symbol]['close'], 'changed_open_cells': changed[symbol]['open'],
                           'crossing_training_origins_excluded': crossing,
                           'training_origins_with_quarantined_lookback': affected_lookbacks})
    return {'passed': True, 'original_panel_sha256': sha(source_path), 'derived_panel_sha256': sha(target_path),
            'protocol_sha256': sha(root / 'quality-protocol.json'), 'receipt_sha256': sha(root / 'quality-receipt.json'),
            'array_cells_compared': total_compared, 'only_declared_mutations': True,
            'evaluation_origins_eligibility_and_outcomes_unchanged': True,
            'model_rules_unchanged': True, 'events': exclusions,
            'scope': 'Conservative training quarantine sensitivity; not corrected corporate-action total returns or an independent holdout.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--universe', choices=['diverse100', 'sp500'], required=True)
    args = parser.parse_args()
    derivation = verify_derivation(args.root, args.universe)
    report = audit(args.root, f'{args.universe}-quality')
    report['quarantine_derivation'] = derivation
    report['quality_verifier_sha256'] = sha(Path(__file__))
    path = args.root / f'{args.universe}-quality' / 'ranking/verification.json'
    with path.open('x') as file:
        json.dump(report, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
