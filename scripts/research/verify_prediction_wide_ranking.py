"""Independent chronology/numerics audit for wide-universe ranking artifacts."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid(value):
    return value is not None and math.isfinite(value) and value > 0


def eligible_at(panel, t):
    mask = panel.get('membership')
    indices = []
    members = 0
    for j, s in enumerate(panel['symbols']):
        member = mask is None or mask[t][j]
        if not member:
            continue
        members += 1
        if t >= 252 and all(valid(v) for field in ('close', 'volume') for v in panel['series'][s][field][t - 252:t + 1]):
            indices.append(j)
    return indices, members


def independent_features(panel, t, indices):
    raw = []
    for j in indices:
        series = panel['series'][panel['symbols'][j]]
        c, v = series['close'], series['volume']
        daily = [c[k] / c[k - 1] - 1 for k in range(t - 62, t + 1)]
        raw.append([c[t] / c[t - 5] - 1, c[t] / c[t - 21] - 1, c[t] / c[t - 63] - 1,
                    c[t - 21] / c[t - 126] - 1, c[t - 21] / c[t - 252] - 1,
                    statistics.stdev(daily[-21:]), statistics.stdev(daily),
                    c[t] / max(c[t - 62:t + 1]) - 1,
                    statistics.fmean(v[t - 4:t + 1]) / statistics.fmean(v[t - 62:t + 1]) - 1,
                    math.log(statistics.fmean(c[k] * v[k] for k in range(t - 20, t + 1)))])
    return 2 * (rankdata(raw, axis=0, method='average') - 1) / (len(indices) - 1) - 1


def audit(root, universe):
    panel_path = root / f'panel-{universe}.json'
    prediction_path = root / universe / 'ranking/predictions.json'
    outcome_path = root / universe / 'ranking/outcomes.json'
    panel = json.loads(panel_path.read_text())
    frozen = json.loads(prediction_path.read_text())
    outcome_file = json.loads(outcome_path.read_text())
    require(frozen['metadata']['panel_sha256'] == sha(panel_path) == outcome_file['panel_sha256'], 'Panel identity mismatch')
    require(outcome_file['predictions_sha256'] == sha(prediction_path), 'Outcome forecast linkage mismatch')
    require('outcomes' not in frozen, 'Outcomes embedded in forecasts')
    require(frozen['metadata']['symbols'] == panel['symbols'], 'Universe order mismatch')
    models = ('momentum_12_1', 'ridge', 'hgb')
    require(tuple(frozen['metadata']['models']) == models, 'Model identity mismatch')
    require(not frozen['failures'], 'Native run has failures that need manual audit')
    final = panel['dates'].index('2026-09-04')
    first = next(t for t, d in enumerate(panel['dates']) if t >= 252 and d >= '2021-09-03')
    require([r['origin_index'] for r in frozen['rows']] == list(range(first, final - 1, 21)), 'Evaluation origin coverage differs')
    training_lookup = {r['origin_index']: r for r in frozen['training_coverage']}
    require(len(training_lookup) == len(frozen['training_coverage']), 'Duplicate training coverage records')
    independent_training = {}
    for o, saved in training_lookup.items():
        indices, members = eligible_at(panel, o)
        resolved = [j for j in indices if valid(panel['series'][panel['symbols'][j]]['open'][o + 1])
                    and valid(panel['series'][panel['symbols'][j]]['open'][o + 22])]
        usable = len(indices) >= 2 and len(resolved) >= 2
        expected = {'date': panel['dates'][o], 'member_count': members, 'eligible_count': len(indices),
                    'excluded_incomplete_history': members - len(indices), 'exit_index': o + 22,
                    'resolved_label_count': len(resolved) if len(indices) >= 2 else 0,
                    'excluded_unresolved_labels': len(indices) - len(resolved) if len(indices) >= 2 else 0,
                    'usable': usable}
        require(all(saved[k] == v for k, v in expected.items()), f'Training coverage mismatch at {o}')
        independent_training[o] = {'indices': indices, 'resolved': resolved, 'usable': usable}
    outcomes = {(r['origin_index'], r['symbol']): r for r in outcome_file['outcomes']}
    require(len(outcomes) == len(outcome_file['outcomes']), 'Duplicate outcome rows')
    coverage = {r['origin_index']: r for r in frozen['coverage']}
    require(len(coverage) == len(frozen['rows']), 'Coverage rows differ')
    max_momentum = max_outcome = max_relative = 0.
    unresolved = 0
    for row in frozen['rows']:
        t = row['origin_index']
        indices, members = eligible_at(panel, t)
        symbols = [panel['symbols'][j] for j in indices]
        require(row['eligible_symbols'] == symbols, f'Prediction eligibility mismatch at {t}')
        require(coverage[t]['member_count'] == members and coverage[t]['eligible_count'] == len(indices)
                and coverage[t]['excluded_incomplete_history'] == members - len(indices), 'Decision coverage counts mismatch')
        require(row['date'] == panel['dates'][t] and row['entry_index'] == t + 1
                and row['exit_index'] == min(t + 22, final) and row['truncated'] == (t + 22 > final), 'Decision horizon mismatch')
        mature = [o for o in range(252, t + 1, 21) if o + 22 <= t]
        usable = [o for o in mature if independent_training[o]['usable']]
        require(len(usable) >= 24, 'Insufficient training origins')
        expected = {'training_origin_count': len(usable), 'mature_training_origin_count': len(mature),
                    'training_row_count': sum(len(independent_training[o]['resolved']) for o in usable),
                    'last_training_origin': usable[-1], 'last_training_exit_index': usable[-1] + 22,
                    'excluded_training_origins': len(mature) - len(usable),
                    'excluded_unresolved_training_labels': sum(training_lookup[o]['excluded_unresolved_labels'] for o in mature)}
        require(all(row[k] == v for k, v in expected.items()), f'Prediction training maturity mismatch at {t}')
        require(set(row['scores']) == set(models) and all(len(row['scores'][m]) == len(symbols) for m in models), 'Incomplete model coverage')
        observed = []
        for s, score in zip(symbols, row['scores']['momentum_12_1']):
            c = panel['series'][s]['close']
            max_momentum = max(max_momentum, abs(score - (c[t - 21] / c[t - 252] - 1)))
            opens = panel['series'][s]['open']
            observed.append(opens[row['exit_index']] / opens[t + 1] - 1 if valid(opens[t + 1]) and valid(opens[row['exit_index']]) else None)
        complete = all(v is not None for v in observed)
        mean = statistics.fmean(observed) if complete else None
        for s, value in zip(symbols, observed):
            saved = outcomes[t, s]
            require(saved['date'] == row['date'] and saved['entry_index'] == row['entry_index']
                    and saved['exit_index'] == row['exit_index'] and saved['truncated'] == row['truncated'], 'Outcome horizon differs')
            require(saved['state'] == ('resolved' if value is not None else 'unresolved'), 'Outcome availability differs')
            if value is None:
                unresolved += 1
                require(saved['return'] is None, 'Unavailable outcome fabricated')
            else:
                max_outcome = max(max_outcome, abs(value - saved['return']))
            if complete:
                max_relative = max(max_relative, abs(value - mean - saved['relative_return']))
            else:
                require(saved['relative_return'] is None, 'Incomplete universe assigned relative outcome')
    require(len(outcomes) == sum(len(r['eligible_symbols']) for r in frozen['rows']), 'Extra or missing evaluation outcomes')
    require(max(max_momentum, max_outcome, max_relative) < 1e-13, 'Saved outcome or momentum mismatch')
    checks, feature_cache = [], {}
    for row in (frozen['rows'][0], frozen['rows'][-1]):
        t = row['origin_index']
        mature = [o for o in range(252, t + 1, 21) if o + 22 <= t and independent_training[o]['usable']]
        xs, ys = [], []
        for o in mature:
            info = independent_training[o]
            if o not in feature_cache:
                feature_cache[o] = independent_features(panel, o, info['indices'])
            resolved_positions = [info['indices'].index(j) for j in info['resolved']]
            xs.append(feature_cache[o][resolved_positions])
            returns = [panel['series'][panel['symbols'][j]]['open'][o + 22] / panel['series'][panel['symbols'][j]]['open'][o + 1] - 1 for j in info['resolved']]
            mean = statistics.fmean(returns)
            ys.extend(v - mean for v in returns)
        x, y = np.concatenate(xs), np.asarray(ys)
        indices, _ = eligible_at(panel, t)
        features = independent_features(panel, t, indices)
        estimators = {
            'ridge': Ridge(alpha=len(x), fit_intercept=True, solver='svd').fit(x, y),
            'hgb': HistGradientBoostingRegressor(loss='squared_error', max_iter=100, learning_rate=.03,
                max_depth=2, max_leaf_nodes=4, min_samples_leaf=50, l2_regularization=1,
                early_stopping=False, random_state=59137).fit(x, y),
        }
        for name, estimator in estimators.items():
            difference = float(np.max(np.abs(estimator.predict(features) - np.array(row['scores'][name]))))
            require(difference < 1e-12, f'Independent {name} reconstruction differs at {row["date"]}: {difference}')
            checks.append({'date': row['date'], 'model': name, 'eligible_stocks': len(indices),
                           'training_origins': len(mature), 'training_rows': len(x), 'max_absolute_difference': difference})
    # Separately exercise production feature causality against actual panel tails.
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.research.prediction_wide_ranking import Panel
    production = Panel(panel)
    causality = []
    for row in (frozen['rows'][0], frozen['rows'][-1]):
        t = row['origin_index']
        altered = {**panel, 'series': {s: {**fields, **{field: fields[field][:t + 1] + [None] * (len(panel['dates']) - t - 1)
                    for field in ('open', 'close', 'volume')}} for s, fields in panel['series'].items()}}
        original = production.features(t)
        changed = Panel(altered).features(t)
        require(np.array_equal(original[0], changed[0]) and np.array_equal(original[1], changed[1]), 'Actual future perturbation changes features')
        indices, _ = eligible_at(panel, t)
        require(np.array_equal(original[1], independent_features(panel, t, indices)), 'Production features differ from scalar reconstruction')
        causality.append({'date': row['date'], 'all_future_open_close_volume_removed': True, 'eligibility_and_features_unchanged': True})
    return {'passed': True, 'universe': universe, 'panel_sha256': sha(panel_path),
            'predictions_sha256': sha(prediction_path), 'outcomes_sha256': sha(outcome_path), 'verifier_sha256': sha(Path(__file__)),
            'origins': len(frozen['rows']), 'training_origins_verified': len(training_lookup),
            'verified_momentum_scores': len(outcomes), 'verified_outcomes': len(outcomes), 'unresolved_outcomes': unresolved,
            'truncated_origins': sum(r['truncated'] for r in frozen['rows']),
            'mature_training_labels_excluded_at_final_origin': frozen['rows'][-1]['excluded_unresolved_training_labels'],
            'max_momentum_difference': max_momentum, 'max_outcome_difference': max_outcome, 'max_relative_difference': max_relative,
            'learned_prediction_checks': checks, 'actual_panel_feature_causality': causality,
            'scope': 'All chronology, eligibility, label exclusions and outcomes checked; first/last learned-model origins independently refitted. Survivor-selected universe and revised-data limitations remain.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--universe', required=True, choices=['diverse100', 'sp500'])
    args = parser.parse_args()
    report = audit(args.root, args.universe)
    path = args.root / args.universe / 'ranking/verification.json'
    with path.open('x') as file:
        json.dump(report, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
