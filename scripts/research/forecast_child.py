"""Offline, disposable TimesFM process. Receives numerical inputs, never credentials."""
import argparse
import importlib.metadata
import json
import resource
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    parser.add_argument("output")
    parser.add_argument("model")
    parser.add_argument("--device", choices=["cpu", "mps"], default="cpu")
    args = parser.parse_args()
    started = time.perf_counter()
    import numpy as np
    import torch
    from timesfm3 import ModelConfig, TimesFM3Evaluator

    distribution = importlib.metadata.distribution('timesfm')
    source = json.loads(distribution.read_text('direct_url.json') or '{}')
    if source.get('vcs_info', {}).get('commit_id') != '0df95ae62085a6ac0d0afd1ad40dee2e6c1356ab':
        raise RuntimeError('Installed TimesFM code differs from the reviewed revision')

    torch.set_num_threads(8)
    torch.set_num_interop_threads(2)
    if args.device == "mps" and not torch.backends.mps.is_available():
        raise RuntimeError("Apple GPU unavailable")
    packet = json.loads(Path(args.input).read_text())
    model = TimesFM3Evaluator(ModelConfig(checkpoint_path=args.model,
        device=args.device, per_core_batch_size=1, local_files_only=True))
    load_seconds = time.perf_counter() - started
    results = []
    for case in packet["cases"]:
        values = np.asarray(case["values"], dtype=np.float32)
        if values.shape != (256,) or not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError("Expected 256 finite, positive daily prices")
        cov = case.get("covariates")
        cov = None if cov is None else np.asarray(cov, dtype=np.float32)
        if cov is not None and (cov.shape != (2, 256) or not np.isfinite(cov).all()):
            raise ValueError("Expected two aligned past-only covariates")
        start = time.perf_counter()
        outputs = list(model.predict_batch([values], horizon=packet["horizon"],
            past_only_covariates=[cov] if cov is not None else None,
            return_quantiles=True, use_symmetric_averaging=False,
            make_positive=True, sort_quantiles=True))
        if args.device == "mps":
            torch.mps.synchronize()
        output = outputs[0]
        forecast = np.asarray(output.forecast).reshape(packet["horizon"])
        quantiles = np.asarray(output.quantiles).reshape(packet["horizon"], 9)
        if not np.isfinite(forecast).all() or not np.isfinite(quantiles).all():
            raise ValueError("Model returned non-finite forecasts")
        results.append({"forecast": forecast.tolist(), "quantiles": quantiles.tolist(),
                        "inference_seconds": time.perf_counter() - start})
    # macOS reports bytes; Linux reports KiB. This excludes some accelerator allocations.
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    result = {"device": args.device, "torch_version": torch.__version__,
        "timesfm_version": distribution.version, "numpy_version": np.__version__,
        "timesfm_code_revision": source['vcs_info']['commit_id'],
        "load_seconds": load_seconds, "total_seconds": time.perf_counter() - started,
        "peak_process_rss_mb": rss / (1024 ** 2 if sys.platform == "darwin" else 1024),
        "mps_allocated_mb": torch.mps.driver_allocated_memory()/1024**2 if args.device == "mps" else None,
        "results": results}
    Path(args.output).write_text(json.dumps(result, allow_nan=False))


if __name__ == "__main__":
    main()
