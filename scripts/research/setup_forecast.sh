#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../.."
uv venv --python .venv/bin/python .venv-timesfm
uv pip install --python .venv-timesfm/bin/python \
  'timesfm[torch] @ git+https://github.com/google-research/timesfm.git@0df95ae62085a6ac0d0afd1ad40dee2e6c1356ab' \
  'torch==2.14.0' 'numpy==2.5.2' 'huggingface-hub==1.30.0' 'safetensors==0.8.0'
.venv-timesfm/bin/python - <<'PY'
from huggingface_hub import snapshot_download
snapshot_download('google/timesfm-3.0-pytorch',
    revision='43046b85ec22d584a13f8098c2ed39c889e129c2',
    local_dir='.research-artifacts/forecast/model')
PY
.venv-timesfm/bin/python scripts/research/register_forecast_runtime.py
