"""One tool-free design call. Only the selected credential arrives through stdin."""
import json
from pathlib import Path
import sys

from tradingagents.research.contracts import canonical_json
from tradingagents.research.designer import DesignInput, validate_completion
from tradingagents.research.evidence.provider import ProviderBinding, ProviderExtractionClient


def main(output: Path):
    try:
        raw = sys.stdin.buffer.read(300001)
        if len(raw) > 300000:
            raise ValueError("Oversized dispatch envelope")
        payload = json.loads(raw)
        saved = payload["request"]
        request = DesignInput.model_validate(saved["input"])
        client = ProviderExtractionClient(ProviderBinding(**payload["binding"]), request.policy, payload.pop("credential"))
        completion = client.complete(system=saved["system"], user=saved["user"], schema=saved["schema"])
        output.write_text(canonical_json(validate_completion(completion, request)))
    except Exception:
        raise SystemExit(1) from None


if __name__ == "__main__":
    main(Path(sys.argv[1]))
