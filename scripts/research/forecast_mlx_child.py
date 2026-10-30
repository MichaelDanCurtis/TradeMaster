"""Offline FP32 MLX adapter; reuses the pinned MIT mlx-tsfm port (see docs).

Supports only Forecast Lab's 256 daily closes, 5/20 horizons and two optional
past-only covariates. No future covariates, weight download, or device fallback.
"""
import argparse
import hashlib
import importlib.metadata
import json
import resource
import platform
import sys
import time
from pathlib import Path

PORT_REVISION = 'be63b266d7065177c8bd5b163a954d3ab3c66221'
CONFIG_SHA256 = 'ff17bbc07b792c5a904cca265b8468579d736a4fe84981da25eb871b0a125bc6'



def sum_fp32_256(values):
    """Match the pinned PyTorch ARM NEON contiguous sum order for 256 values.

    Four interleaved vectors, four FP32 lanes, 16 sequential additions, then
    sequential vector/lane folds. This is the size-256 specialization of
    PyTorch SumKernel.cpp's vectorized_inner_sum/row_sum (BSD-3-Clause;
    license preserved in docs/third-party/PYTORCH_LICENSE.txt). It is not a more
    accurate replacement: preserving the reference rounding matters when a
    nearly linear input is later standardized. See docs/TIMESFM_MLX.md.
    """
    import numpy as np
    values = np.asarray(values, dtype=np.float32)
    if values.shape[-1] != 256:
        raise ValueError('Qualified reduction requires 256 observations')
    blocks = values.reshape(*values.shape[:-1], 16, 4, 4)
    accum = np.zeros((*values.shape[:-1], 4, 4), dtype=np.float32)
    for i in range(16):
        accum = accum + blocks[..., i, :, :]
    folded = accum[..., 0, :]
    for i in range(1, 4):
        folded = folded + accum[..., i, :]
    result = np.zeros(values.shape[:-1], dtype=np.float32)
    for i in range(4):
        result = result + folded[..., i]
    return result


def reference_detrend(values, masks, context):
    """FP32 CPU preprocessing matching the pinned Google/PyTorch ARM reference.

    NumPy executes the small reductions in a prescribed order; weights and the
    transformer stay on MLX Metal. No input-dependent model/device fallback.
    """
    import numpy as np
    x = np.asarray(values, dtype=np.float32)
    mask = np.asarray(masks, dtype=bool)
    if context != 256 or x.shape != mask.shape or x.ndim != 3:
        raise ValueError('Unsupported detrending shape')
    valid = ~mask
    t = np.arange(-255, 1, dtype=np.float32) / np.float32(context)
    n = sum_fp32_256(valid.astype(np.float32))
    safe_n = np.maximum(n, np.float32(1))
    st = sum_fp32_256(np.where(valid, t, np.float32(0)))
    st2 = sum_fp32_256(np.where(valid, t*t, np.float32(0)))
    sy = sum_fp32_256(np.where(valid, x, np.float32(0)))
    sty = sum_fp32_256(np.where(valid, t*x, np.float32(0)))
    det = n*st2 - st*st
    safe_det = np.where(det == 0, np.float32(1), det)
    m = np.where(det == 0, np.float32(0), (n*sty-st*sy)/safe_det)
    c = np.where(det == 0, np.where(n > 0, sy/safe_n, np.float32(0)), (sy-m*st)/safe_n)
    residual = x - (m[..., None]*t+c[..., None])
    mean = sy/safe_n
    std = np.sqrt(np.maximum(sum_fp32_256(np.where(valid,x*x,np.float32(0)))/safe_n-mean*mean,np.float32(0)))
    mean_d = sum_fp32_256(np.where(valid,residual,np.float32(0)))/safe_n
    std_d = np.sqrt(np.maximum(sum_fp32_256(np.where(valid,residual*residual,np.float32(0)))/safe_n-mean_d*mean_d,np.float32(0)))
    return m, c, std_d < np.float32(.5)*std


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('input')
    parser.add_argument('output')
    parser.add_argument('model')
    parser.add_argument('--device', choices=['mlx'], default='mlx')
    args = parser.parse_args()
    started = time.perf_counter()
    import numpy as np
    import mlx.core as mx
    from mlx_tsfm.models.timesfm import TimesFM3

    if sys.platform != 'darwin' or platform.machine() != 'arm64':
        raise RuntimeError('Qualified MLX preprocessing requires Apple Silicon macOS')
    if np.__version__ != '2.5.2' or importlib.metadata.version('mlx') != '0.32.2':
        raise RuntimeError('Install the qualified NumPy and MLX versions with setup_forecast_mlx.sh')
    distribution = importlib.metadata.distribution('mlx-tsfm')
    source = json.loads(distribution.read_text('direct_url.json') or '{}')
    if source.get('vcs_info', {}).get('commit_id') != PORT_REVISION:
        raise RuntimeError('Installed MLX port differs from the reviewed revision')
    if not mx.metal.is_available():
        raise RuntimeError('MLX Metal device unavailable')
    mx.set_default_device(mx.gpu)
    model_path = Path(args.model)
    if hashlib.sha256((model_path/'config.json').read_bytes()).hexdigest() != CONFIG_SHA256:
        raise ValueError('Checkpoint configuration is outside the qualified MLX architecture')
    packet = json.loads(Path(args.input).read_text())
    horizon = packet['horizon']
    if type(horizon) is not int or horizon not in (5, 20):
        raise ValueError('MLX adapter supports only 5 or 20 sessions')
    model = TimesFM3()
    # Native strict loading checks every name and shape, without a NumPy copy of
    # the entire checkpoint. Keep original FP32 weights; no quantization.
    model.load_weights(str(model_path/'model.safetensors'), strict=True)
    mx.eval(model.parameters())
    model._detrend = lambda values, masks, context: tuple(mx.array(x) for x in reference_detrend(values, masks, context))
    load_seconds = time.perf_counter() - started
    results = []
    for case in packet['cases']:
        values = np.asarray(case['values'], dtype=np.float32)
        if values.shape != (256,) or not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError('Expected 256 finite, positive daily prices')
        cov = case.get('covariates')
        cov = None if cov is None else np.asarray(cov, dtype=np.float32)
        if cov is not None and (cov.shape != (2, 256) or not np.isfinite(cov).all()):
            raise ValueError('Expected two aligned past-only covariates')
        start = time.perf_counter()
        # Google decode gives targets and past-only covariates identical future
        # masks and patch_is_target flags. Decode all three, retain target zero.
        combined = values[None, :] if cov is None else np.concatenate([values[None, :], cov])
        raw = model.decode(mx.array(combined[None, :, :]), horizon)[0, 0]
        mx.eval(raw)  # Metal is lazy: include completed inference in the timer.
        quantiles = np.maximum(np.sort(np.asarray(raw), axis=-1), 0)
        forecast = quantiles[:, 4]  # Match Google's post-sort median semantics.
        if quantiles.shape != (horizon, 9) or not np.isfinite(quantiles).all():
            raise ValueError('Model returned invalid forecasts')
        results.append({'forecast': forecast.tolist(), 'quantiles': quantiles.tolist(),
                        'inference_seconds': time.perf_counter() - start})
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {'device': 'mlx', 'mlx_version': importlib.metadata.version('mlx'),
        'mlx_port_version': distribution.version, 'mlx_port_revision': PORT_REVISION,
        'numpy_version': np.__version__, 'preprocessing': 'numpy-fp32-pytorch-arm256-v1',
        'preprocessing_reference': 'PyTorch 2.14.0 ARM CPU / 08187d9e0fba026dc8217405802ab5381dc88d90', 'precision': 'float32', 'compiled': True,
        'load_seconds': load_seconds, 'total_seconds': time.perf_counter() - started,
        'peak_process_rss_mb': rss / (1024 ** 2 if sys.platform == 'darwin' else 1024),
        'mlx_peak_allocated_mb': mx.get_peak_memory() / 1024**2, 'mps_allocated_mb': None,
        'results': results}
    Path(args.output).write_text(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
