#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
if [[ "$(uname -s)" != Darwin || "$(uname -m)" != arm64 ]]; then
  echo 'The MLX forecast runtime requires an Apple Silicon Mac.' >&2
  exit 1
fi
test -f .research-artifacts/forecast/model/model.safetensors || {
  echo 'Install the base Forecast Lab model first with setup_forecast.sh.' >&2
  exit 1
}
uv venv --python .venv/bin/python .venv-timesfm-mlx
uv pip install --python .venv-timesfm-mlx/bin/python \
  'mlx==0.32.2' 'mlx-metal==0.32.2' 'numpy==2.5.2' 'safetensors==0.8.0'
# The numeric TimesFM module does not use the port's optional LLM dependencies.
uv pip install --python .venv-timesfm-mlx/bin/python --no-deps \
  'mlx-tsfm @ git+https://github.com/rachittshah/mlx-tsfm.git@be63b266d7065177c8bd5b163a954d3ab3c66221'
.venv-timesfm-mlx/bin/python - <<'PY'
import mlx.core as mx
from mlx_tsfm.models.timesfm import TimesFM3
assert mx.metal.is_available(), 'Metal unavailable; no CPU fallback'
print('MLX Metal imports verified. Forecasts reuse the existing local FP32 checkpoint.')
PY
