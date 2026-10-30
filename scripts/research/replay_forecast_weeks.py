"""Replay chosen historical weeks from verified saved data, without future model inputs."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))

from tradingagents.ui.forecast_data import experiment_cases, metrics, comparison_summary
from tradingagents.ui.forecast_lab import ForecastLab


def historical_cases(source, week_starts):
    cases, outcomes = [], []
    for week in week_starts:
        first = date.fromisoformat(week)
        if first.weekday() != 0:
            raise ValueError('Select a Monday as the start of each historical week')
        if (first + timedelta(days=4)).isoformat() > source['end']:
            raise ValueError('Requested week exceeds the preserved source window')
        historical = {**source, 'end': (first-timedelta(days=1)).isoformat()}
        for case in experiment_cases(historical, 5, 'prospective', 'compare'):
            if case['target_dates'][0] != week or case['target_dates'][-1] > (first+timedelta(days=4)).isoformat():
                raise ValueError('Selected calendar week must contain five trading sessions')
            if max(case['dates']) >= min(case['target_dates']):
                raise ValueError('Forecast inputs overlap the target week')
            cases.append(case)
            # Outcomes remain separate from the model-input packet.
            outcomes.append([source['bars'][source['symbol']][d]['close'] for d in case['target_dates']])
    return cases, outcomes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input-hash', required=True)
    parser.add_argument('--weeks', nargs='+', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'mlx'], default='mlx')
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Use a new output directory to preserve prior results')
    lab = ForecastLab(None, None)
    source = lab.store.json(args.input_hash)
    cases, outcomes = historical_cases(source, args.weeks)
    manifest = lab.runtime()['manifest']
    for name, expected in manifest['files'].items():
        with (lab.root/'model'/name).open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('Installed model differs from its saved manifest')
    args.output.mkdir(parents=True)
    model_input = {'horizon': 5, 'cases': [{'values': c['values'], 'covariates': c['covariates']} for c in cases]}
    input_bytes = json.dumps(model_input).encode()
    (args.output/'model-input.json').write_bytes(input_bytes)
    intent = {'source_input_hash': args.input_hash, 'weeks': args.weeks, 'symbol': source['symbol'],
        'created_at': datetime.now(timezone.utc).isoformat(), 'device': args.device,
        'model_input_sha256': hashlib.sha256(input_bytes).hexdigest(), 'model': manifest,
        'cutoffs': [c['cutoff'] for c in cases], 'prospective_eligible': False,
        'scope': 'Historical replay selected before this inference; current data revisions and model pretraining overlap remain possible.'}
    (args.output/'intent.json').write_text(json.dumps(intent, indent=2)+'\n')
    output = lab.infer({'horizon': 5, 'cases': cases}, args.device)
    (args.output/'model-output.json').write_text(json.dumps(output, indent=2)+'\n')
    scores = [metrics(c, prediction, actual) for c, prediction, actual in zip(cases, output['results'], outcomes)]
    rows = []
    for case, prediction, actual, score in zip(cases, output['results'], outcomes, scores):
        rows.append({'variant': case['variant'], 'cutoff': case['cutoff'], 'metrics': score,
            'days': [{'date': day, 'actual': a, 'forecast': p, 'flat': b, 'drift': d,
                      'q10': q[0], 'q90': q[8]}
                for day, a, p, b, d, q in zip(case['target_dates'], actual, prediction['forecast'],
                    case['baseline'], case['drift_baseline'], prediction['quantiles'])]})
    report = {**intent, 'completed_at': datetime.now(timezone.utc).isoformat(), 'cases': rows,
        'comparison': comparison_summary(cases, scores),
        'limitations': ['Two selected historical weeks cannot establish persistent forecasting skill.',
            'Price-error scores do not measure strategy profit, transaction costs or broker fills.',
            'Only the 256 sessions before each cutoff enter inference, including auxiliary prices and volume.']}
    (args.output/'report.json').write_text(json.dumps(report, indent=2)+'\n')
    lines = [f"# {source['symbol']} historical forecast comparison", '',
        'Each forecast uses 256 sessions ending before the target week. Lower mean absolute error (MAE) is better.', '',
        '| Week | Inputs | TimesFM MAE | Flat-price MAE | Drift MAE | 10–90% band coverage |',
        '| --- | --- | ---: | ---: | ---: | ---: |']
    for row in rows:
        m = row['metrics']
        lines.append(f"| {row['days'][0]['date']}–{row['days'][-1]['date']} | {row['variant']} | ${m['mae_usd']:.2f} | ${m['baseline_mae_usd']:.2f} | ${m['drift_mae_usd']:.2f} | {m['interval_coverage_pct']:.0f}% |")
    lines.extend(['', 'Historical replay, not a forecast issued before these weeks occurred.', '', *report['limitations']])
    (args.output/'report.md').write_text('\n'.join(lines)+'\n')
    print(json.dumps({'output': str(args.output.resolve()), 'comparison': report['comparison']}, indent=2))


if __name__ == '__main__':
    main()
