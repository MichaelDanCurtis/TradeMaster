"""Isolated, killable Codex brief call. No broker credentials enter this child."""
import json
from pathlib import Path
import sys

from tradingagents.research.contracts import canonical_json
from tradingagents.research.evidence.provider import ProviderBinding, ProviderExtractionClient
from tradingagents.ui.explorer_briefs import BriefProposal, SYSTEM, brief_policy, validate_brief


def main(output):
    raw = sys.stdin.buffer.read(100001)
    if len(raw) > 100000:
        raise ValueError("Oversized brief packet")
    payload = json.loads(raw)
    binding = ProviderBinding(**payload["binding"])
    try:
        from tradingagents.ui.evidence_attachments import attachment_store
        sources = [s for s in payload['packet']['sources'] if s.get('kind') in ('chart_image','pdf_page')]
        if len(sources) > 4:
            raise ValueError('Too many supplied image pages')
        images = [(s['source_id'], attachment_store().get(s['image_sha256'])) for s in sources]
        client = ProviderExtractionClient(binding, brief_policy(len(images)), "local-research-no-auth")
        system, schema, validator = SYSTEM, BriefProposal, validate_brief
        if payload['packet'].get('purpose') == 'thesis_challenge':
            from tradingagents.ui.thesis_challenge import CHALLENGE_SYSTEM, ChallengeProposal, validate_challenge
            system, schema, validator = CHALLENGE_SYSTEM, ChallengeProposal, validate_challenge
        if payload['packet'].get('purpose') == 'historical_replay':
            from tradingagents.ui.historical_replay import HISTORICAL_SYSTEM
            system = HISTORICAL_SYSTEM
        completion = client.complete(system=system, user=canonical_json(payload["packet"]), schema=schema.model_json_schema(),
                                     **({'images': images} if images else {}))
        receipt = validator(completion, payload["packet"], binding)
        receipt['visual_inputs'] = [{'source_id': s['source_id'], 'sha256': s['image_sha256']} for s in sources]
    except Exception as exc:
        known = {
            "Codex research turn did not complete": "Codex returned an incomplete research turn.",
            "Codex research deadline expired; no automatic retry": "Codex did not finish within the research deadline.",
            "Codex stopped without a completed research receipt": "The Codex connection ended before a complete receipt.",
            "Source packet exceeds the frozen conservative input-token bound": "The evidence exceeds the reviewed input size.",
            "Sign in to Codex with ChatGPT; API-key fallback is disabled": "Codex ChatGPT sign-in is required.",
        }
        reason = known.get(str(exc), "Codex did not return a usable research receipt (" + type(exc).__name__ + ").")
        receipt = {"proposal": None, "validation_errors": [reason], "input_tokens": None, "output_tokens": None,
                   "actual_model_id": "unconfirmed", "dispatch_failure": reason}
    output.write_text(canonical_json(receipt))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
