"""Compare completed FP32 outputs and sequential fresh-process backend timings.

Usage: .venv/bin/python scripts/research/benchmark_forecast_backends.py INPUT_DIR
INPUT_DIR contains input-5.json and input-20.json (numerical cases only).
This does not fetch market data, change app settings, or submit any orders.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
ATOL, RTOL = 0.001, 0.00001  # Declared before measuring; never tuned to outputs.


def mlx_qualified(summary):
    return all(any(s['device'] == 'mlx' and s['variant'] == variant and s['passed'] for s in summary)
               for variant in ('stock', 'market_volume'))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('inputs', type=Path)
    parser.add_argument('--repeats', type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error('Use at least two fresh processes per backend and horizon')
    folder = args.inputs.resolve()
    env = {k: v for k, v in os.environ.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'SYSTEMROOT')}
    env.update(HF_HUB_OFFLINE='1', HF_HUB_DISABLE_TELEMETRY='1',
               PYTORCH_ENABLE_MPS_FALLBACK='0', OMP_NUM_THREADS='8')
    runs, checks, timings = [], [], []
    devices = ['cpu', 'mps', 'mlx']
    for horizon in (5, 20):
        packet = json.loads((folder/f'input-{horizon}.json').read_text())
        if packet['horizon'] != horizon:
            raise ValueError('Input file horizon mismatch')
        reference = None
        for repeat in range(args.repeats):
            # Rotate order after the first reference run to reduce order bias.
            order = devices[repeat % 3:] + devices[:repeat % 3]
            for device in order:
                mlx = device == 'mlx'
                runner = ROOT/'scripts/research'/('forecast_mlx_child.py' if mlx else 'forecast_child.py')
                interpreter = ROOT/('.venv-timesfm-mlx' if mlx else '.venv-timesfm')/'bin/python'
                output = folder/f'{device}-{horizon}-repeat{repeat}.json'
                started = time.perf_counter()
                with output.with_suffix('.log').open('w') as log:
                    subprocess.run([str(interpreter), '-I', str(runner),
                        str(folder/f'input-{horizon}.json'), str(output),
                        str(ROOT/'.research-artifacts/forecast/model'), '--device', device],
                        env=env, cwd=folder, stdout=log, stderr=log, timeout=180, check=True)
                wall = time.perf_counter() - started
                result = json.loads(output.read_text())
                if len(result['results']) != len(packet['cases']):
                    raise ValueError('Output case count differs')
                if reference is None:
                    assert device == 'cpu'
                    reference = result['results']
                metadata = {k: v for k, v in result.items() if k != 'results'}
                runs.append({'horizon': horizon, 'repeat': repeat, 'device': device,
                    'process_wall_seconds': wall, 'runtime': metadata,
                    'output_sha256': hashlib.sha256(output.read_bytes()).hexdigest()})
                seen = set()
                for index, (case, actual, expected) in enumerate(zip(packet['cases'], result['results'], reference)):
                    variant = 'stock' if case.get('covariates') is None else 'market_volume'
                    first_shape = variant not in seen
                    seen.add(variant)
                    timings.append({'device': device, 'horizon': horizon, 'variant': variant,
                        'first_shape': first_shape, 'seconds': actual['inference_seconds']})
                    lhs = actual['forecast'] + [v for row in actual['quantiles'] for v in row]
                    rhs = expected['forecast'] + [v for row in expected['quantiles'] for v in row]
                    if len(lhs) != horizon*10 or len(rhs) != horizon*10:
                        raise ValueError('Wrong point/quantile shape')
                    checks.append({'device': device, 'horizon': horizon, 'repeat': repeat,
                        'case': case.get('label', str(index)), 'variant': variant,
                        'passed': all(math.isfinite(a) and math.isclose(a, b, abs_tol=ATOL, rel_tol=RTOL)
                                      for a, b in zip(lhs, rhs)),
                        'max_absolute_difference': max(abs(a-b) for a,b in zip(lhs,rhs))})
                print(f'{device} horizon={horizon} repeat={repeat}: process {wall:.3f}s', flush=True)
    summary = []
    for device in devices:
        for variant in ('stock', 'market_volume'):
            samples = sorted(t['seconds'] for t in timings if t['device'] == device and
                             t['variant'] == variant and not t['first_shape'])
            relevant = [c for c in checks if c['device'] == device and c['variant'] == variant]
            summary.append({'device': device, 'variant': variant, 'checks': len(relevant),
                'passed': all(c['passed'] for c in relevant),
                'max_absolute_difference': max(c['max_absolute_difference'] for c in relevant),
                'warm_median_seconds': statistics.median(samples),
                'warm_p95_seconds': samples[math.ceil(.95*len(samples))-1], 'warm_samples': len(samples)})
    report = {'benchmark_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), 'platform': platform.platform(), 'machine': platform.machine(),
        'atol': ATOL, 'rtol': RTOL, 'repeats': args.repeats,
        'scope': '256 FP32 closes, horizons 5/20; stock and two past-only covariates. Filesystem/Metal caches are not cleared.',
        'input_sha256': {str(h): hashlib.sha256((folder/f'input-{h}.json').read_bytes()).hexdigest() for h in (5,20)},
        'model_sha256': hashlib.file_digest((ROOT/'.research-artifacts/forecast/model/model.safetensors').open('rb'), 'sha256').hexdigest(),
        'runner_sha256': {name: hashlib.sha256((ROOT/'scripts/research'/name).read_bytes()).hexdigest()
                          for name in ('forecast_child.py','forecast_mlx_child.py')},
        'summary': summary, 'runs': runs, 'checks': checks, 'timings': timings}
    (folder/'report.json').write_text(json.dumps(report, indent=2, allow_nan=False))
    print(json.dumps(summary, indent=2))
    if not mlx_qualified(summary):
        raise SystemExit('MLX qualification failed for stock or multivariate inputs')


if __name__ == '__main__':
    main()
