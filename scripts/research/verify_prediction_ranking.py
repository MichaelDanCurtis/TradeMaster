"""Independent replay audit of saved ranking forecasts and profit attribution.

Deliberately does not import the ranking or portfolio implementation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np
from scipy.stats import rankdata
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def independent_features(panel, index):
    raw = []
    for symbol in panel['symbols']:
        close = panel['series'][symbol]['close']
        volume = panel['series'][symbol]['volume']
        daily = [close[j] / close[j - 1] - 1 for j in range(index - 62, index + 1)]
        raw.append([
            close[index] / close[index - 5] - 1,
            close[index] / close[index - 21] - 1,
            close[index] / close[index - 63] - 1,
            close[index - 21] / close[index - 126] - 1,
            close[index - 21] / close[index - 252] - 1,
            statistics.stdev(daily[-21:]), statistics.stdev(daily),
            close[index] / max(close[index - 62:index + 1]) - 1,
            statistics.fmean(volume[index - 4:index + 1]) / statistics.fmean(volume[index - 62:index + 1]) - 1,
            math.log(statistics.fmean(close[j] * volume[j] for j in range(index - 20, index + 1))),
        ])
    return 2 * (rankdata(raw, axis=0, method='average') - 1) / (len(raw) - 1) - 1


def attribute(panel, saved, prediction_rows, model, bps):
    names = panel['symbols'] + [panel['benchmark']]
    units = np.zeros(len(names))
    pnl = np.zeros(len(names))
    cost = np.zeros(len(names))
    selected = np.zeros(len(names), dtype=int)
    previous_prices = None
    max_ledger_fee_difference = 0.
    rate = bps / 10000
    for row in saved['ledger']:
        index = row['index']
        prices = np.array([panel['series'][s]['open'][index] for s in names])
        if previous_prices is not None:
            pnl += units * (prices - previous_prices)
        weights = np.array(row['target_weights'])
        if row['kind'] == 'rebalance':
            origin = index - 1
            scores = {r['symbol']: r['score'] for r in prediction_rows if r['model'] == model and r['origin_index'] == origin}
            require(set(scores) == set(panel['symbols']), 'Attribution ranking coverage mismatch')
            top = sorted(range(len(panel['symbols'])), key=lambda j: (-scores[names[j]], j))[:math.ceil(len(panel['symbols']) / 3)]
            expected = np.zeros(len(names))
            expected[top] = 1 / len(top)
            require(np.array_equal(expected, weights), 'Saved ledger does not select predicted top third')
            selected += weights > 0
        else:
            require(row['kind'] == 'liquidation' and np.count_nonzero(weights) == 0, 'Unexpected terminal transaction')
        # Unit changes and cost allocation are reconstructed without portfolio helpers.
        next_values = weights * row['equity_after']
        traded_by_symbol = np.abs(next_values - units * prices)
        allocated = traded_by_symbol * rate
        max_ledger_fee_difference = max(max_ledger_fee_difference, abs(float(allocated.sum()) - row['fees']))
        require(np.isclose(allocated.sum(), row['fees'], atol=1e-12, rtol=0), 'Ledger fee allocation mismatch')
        cost += allocated
        units = next_values / prices
        previous_prices = prices
    require(np.count_nonzero(units) == 0, 'Terminal portfolio not liquidated')
    net = pnl - cost
    discrepancy = float(net.sum() - saved['net_return'])
    require(abs(discrepancy) < 1e-10, 'Attributed profit does not reconcile to portfolio net return')
    rows = [{'symbol': s, 'gross_pnl_fraction_initial_capital': float(pnl[j]),
             'cost_fraction_initial_capital': float(cost[j]),
             'net_pnl_fraction_initial_capital': float(net[j]),
             'share_of_total_net_profit': float(net[j] / saved['net_return']) if saved['net_return'] else None,
             'selected_origins': int(selected[j])} for j, s in enumerate(names)]
    rows.sort(key=lambda r: -r['net_pnl_fraction_initial_capital'])
    return {'model': model, 'cost_bps_per_side': bps, 'net_return': saved['net_return'],
            'total_gross_pnl': float(pnl.sum()), 'total_cost': float(cost.sum()),
            'reconciliation_difference': discrepancy,
            'max_ledger_fee_difference': max_ledger_fee_difference, 'stocks': rows,
            'scope': 'Arithmetic contribution to saved portfolio profit, with actual turnover costs allocated per symbol. Diagnostic only; no stock removal or new experiment.'}


def verify(root):
    panel_path = root / 'panel.json'
    pred_path = root / 'ranking/predictions.json'
    outcomes_path = root / 'ranking/outcomes.json'
    portfolio_path = root / 'portfolios/portfolios.json'
    panel = json.loads(panel_path.read_text())
    frozen = json.loads(pred_path.read_text())
    scored = json.loads(outcomes_path.read_text())
    portfolio = json.loads(portfolio_path.read_text())
    symbols = panel['symbols']
    require(frozen['metadata']['panel_sha256'] == sha(panel_path) == scored['panel_sha256'], 'Panel hash mismatch')
    require(scored['predictions_sha256'] == sha(pred_path), 'Outcome forecast hash mismatch')
    require(portfolio['input_prediction_hashes']['ranking'] == sha(pred_path), 'Portfolio forecast hash mismatch')
    require(portfolio['panel_sha256'] == sha(panel_path), 'Portfolio panel hash mismatch')
    require(frozen['metadata']['symbols'] == symbols and panel['benchmark'] not in symbols, 'Universe mismatch')
    require('outcomes' not in frozen, 'Outcomes embedded in prediction artifact')
    origins = frozen['origins']
    require(len({r['origin_index'] for r in origins}) == len(origins), 'Duplicate origin')
    first_eligible = next(t for t, d in enumerate(panel['dates']) if t >= 252 and d >= '2023-01-03')
    expected_origins = [t for t in range(first_eligible, len(panel['dates']) - 22, 21)
                        if len([o for o in range(252, t + 1, 21) if o + 22 <= t]) >= 24]
    require([r['origin_index'] for r in origins] == expected_origins, 'Origin schedule or coverage differs')
    prediction_lookup = {(r['origin_index'], r['symbol'], r['model']): r for r in frozen['predictions']}
    outcomes_lookup = {(r['origin_index'], r['symbol']): r for r in scored['outcomes']}
    require(len(prediction_lookup) == len(frozen['predictions']) == len(origins) * len(symbols) * 3, 'Prediction duplicates or missing rows')
    require(len(outcomes_lookup) == len(scored['outcomes']) == len(origins) * len(symbols), 'Outcome duplicates or missing rows')
    max_return_error = max_relative_error = max_momentum_error = 0.
    for origin in origins:
        t = origin['origin_index']
        training = [o for o in range(252, t + 1, 21) if o + 22 <= t]
        require(origin['date'] == panel['dates'][t], 'Origin date mismatch')
        expected_fields = {'entry_index': t + 1, 'exit_index': t + 22,
                           'training_origin_count': len(training), 'training_row_count': len(training) * len(symbols),
                           'last_training_origin': training[-1], 'last_training_exit_index': training[-1] + 22}
        require(all(origin[k] == v for k, v in expected_fields.items()), 'Saved training maturity metadata mismatch')
        actual = [panel['series'][s]['open'][t + 22] / panel['series'][s]['open'][t + 1] - 1 for s in symbols]
        average = statistics.fmean(actual)
        for s, value in zip(symbols, actual):
            observed = outcomes_lookup[t, s]
            require(observed['date'] == panel['dates'][t] and observed['entry_index'] == t + 1 and observed['exit_index'] == t + 22, 'Outcome horizon mismatch')
            max_return_error = max(max_return_error, abs(observed['return'] - value))
            max_relative_error = max(max_relative_error, abs(observed['relative_return'] - (value - average)))
            momentum = panel['series'][s]['close'][t - 21] / panel['series'][s]['close'][t - 252] - 1
            max_momentum_error = max(max_momentum_error, abs(prediction_lookup[t, s, 'momentum_12_1']['score'] - momentum))
            for model in ('momentum_12_1', 'ridge', 'hgb'):
                row = prediction_lookup[t, s, model]
                require(all(row[k] == origin[k] for k in origin), 'Prediction training metadata differs from origin')
    require(max_return_error < 1e-14 and max_relative_error < 1e-14 and max_momentum_error < 1e-14, 'Outcome or momentum numeric mismatch')
    learned_checks = []
    for origin in (origins[0], origins[-1]):
        t = origin['origin_index']
        train = [o for o in range(252, t + 1, 21) if o + 22 <= t]
        x = np.concatenate([independent_features(panel, o) for o in train])
        labels = []
        for o in train:
            values = [panel['series'][s]['open'][o + 22] / panel['series'][s]['open'][o + 1] - 1 for s in symbols]
            mean = statistics.fmean(values)
            labels.extend(v - mean for v in values)
        y = np.array(labels)
        test = independent_features(panel, t)
        fitted = {
            'ridge': Ridge(alpha=len(x), fit_intercept=True, solver='svd').fit(x, y),
            'hgb': HistGradientBoostingRegressor(loss='squared_error', max_iter=100, learning_rate=.03,
                 max_depth=2, max_leaf_nodes=4, min_samples_leaf=50, l2_regularization=1,
                 early_stopping=False, random_state=59137).fit(x, y),
        }
        for model, estimator in fitted.items():
            predicted = estimator.predict(test)
            saved = np.array([prediction_lookup[t, s, model]['score'] for s in symbols])
            difference = float(np.max(np.abs(predicted - saved)))
            require(difference < 1e-12, f'Independent {model} mismatch at {origin["date"]}: {difference}')
            learned_checks.append({'date': origin['date'], 'model': model, 'stocks': len(symbols),
                                   'training_origins': len(train), 'training_rows': len(x),
                                   'last_training_exit_index': train[-1] + 22,
                                   'max_absolute_prediction_difference': difference})
    attribution = [attribute(panel, portfolio['cohorts']['ranking']['costs'][str(bps)][model],
                             frozen['predictions'], model, bps) for bps in (11, 22) for model in ('ridge', 'hgb')]
    return {'passed': True, 'panel_sha256': sha(panel_path), 'predictions_sha256': sha(pred_path),
            'outcomes_sha256': sha(outcomes_path), 'portfolios_sha256': sha(portfolio_path),
            'verifier_sha256': sha(Path(__file__)),
            'origin_count': len(origins), 'prediction_count': len(frozen['predictions']),
            'verified_outcome_rows': len(outcomes_lookup), 'verified_momentum_rows': len(outcomes_lookup),
            'max_absolute_return_difference': max_return_error,
            'max_absolute_relative_return_difference': max_relative_error,
            'max_absolute_momentum_difference': max_momentum_error,
            'learned_model_independent_checks': learned_checks, 'profit_attribution': attribution,
            'scope': 'All saved outcomes, momentum scores and maturity metadata verified; first and last learned-model origins independently reconstructed. Does not establish historical data vintage, unbiased universe selection, or future profitability.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.root)
    path = args.root / 'ranking/verification.json'
    with path.open('x') as file:
        json.dump(report, file, indent=2, allow_nan=False)
        file.write('\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('profit_attribution',)}))


if __name__ == '__main__':
    main()
