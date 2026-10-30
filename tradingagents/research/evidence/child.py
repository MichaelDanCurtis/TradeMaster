"""One model call in a killable process. Credentials arrive only through stdin."""
from __future__ import annotations

import json
from pathlib import Path
import sys

from tradingagents.research.contracts import ExtractionPolicy, ModelRevision, SnapshotManifest, canonical_json
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.evidence.extraction import extract
from tradingagents.research.evidence.provider import ProviderBinding, ProviderExtractionClient
from datetime import datetime


def main(output_path: Path):
    try:
        raw = sys.stdin.buffer.read(20001)
        if len(raw) > 20000:
            raise ValueError("Oversized dispatch envelope")
        request = json.loads(raw)
        store = ArtifactStore(request["artifact_root"])
        dataset = store.dataset(SnapshotManifest.model_validate(request["manifest"]))
        notice = next(n for n in dataset.guidance_notices if n.notice_id == request["notice_id"])
        policy = ExtractionPolicy.model_validate(request["policy"])
        model = ModelRevision.model_validate(request["model"])
        binding = ProviderBinding(**request["binding"])
        credential = request.pop("credential")
        client = ProviderExtractionClient(binding, policy, credential)
        result = extract(dataset=dataset, notice=notice, model=model, input_as_of=datetime.fromisoformat(request["input_as_of"]),
            client=client, reserved_cost_usd=policy.maximum_call_cost_usd, mode=policy.availability_mode)
        output_path.write_text(canonical_json(result))
    except Exception:
        # No exception body/traceback from credential handling reaches artifacts.
        sys.stderr.write("Bounded extraction process failed before a usable receipt\n")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main(Path(sys.argv[1]))
