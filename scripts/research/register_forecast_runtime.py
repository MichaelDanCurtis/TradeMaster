"""Record the installed model and optional measured hardware benchmarks."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT/'.research-artifacts/forecast'
files = {name: hashlib.file_digest((ARTIFACTS/'model'/name).open('rb'), 'sha256').hexdigest()
         for name in ['model.safetensors', 'config.json', 'LICENSE']}
manifest = {'model_id': 'google/timesfm-3.0-pytorch',
    'revision': '43046b85ec22d584a13f8098c2ed39c889e129c2',
    'code_revision': '0df95ae62085a6ac0d0afd1ad40dee2e6c1356ab', 'files': files,
    'license_url': 'https://huggingface.co/google/timesfm-3.0-pytorch/blob/43046b85ec22d584a13f8098c2ed39c889e129c2/LICENSE',
    'benchmarks': {}}
for device in ['cpu', 'mps']:
    path = ARTIFACTS/f'benchmark-{device}.json'
    if path.exists():
        result = json.loads(path.read_text())
        manifest['benchmarks'][device] = {k: v for k,v in result.items() if k != 'results'}
        manifest['benchmarks'][device].update(scope='Synthetic 256-point input, 20-session horizon, cold process',
            inference_seconds=result['results'][0]['inference_seconds'])
(ARTIFACTS/'runtime.json').write_text(json.dumps(manifest, indent=2))
print(json.dumps(manifest, indent=2))
