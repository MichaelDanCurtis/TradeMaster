"""Versioned metadata repair over the frozen pilot; preserves every v1 artifact."""
import argparse
from collections import Counter
from copy import deepcopy
import json
from pathlib import Path

from scripts.research.event_research_pilot import check_protocol, digest, now, read, write_new
from scripts.research.verify_event_research_pilot import verify
from tradingagents.research.filing_identity import VERSION, scoped_identity
from tradingagents.research.filing_stability import score_pair


def run(root):
    check_protocol(root); verify(root)
    target = root / "identity-review"
    target.mkdir(exist_ok=False)
    protocol = {"frozen_at": now(), "version": VERSION, "parent_manifest_sha256": digest(root / "manifest.json"),
                "changes": "Scope DEI to non-dimensional target-issuer context at report date; honor explicit numeric date transformation",
                "unchanged": "All original documents, text tokens, Jaccard formula, selections and v1 artifacts",
                "scope": "Engineering repair before any return labels; not a new investment strategy",
                "code_hashes": {str(p.resolve()): digest(p) for p in [Path(__file__), Path("tradingagents/research/filing_identity.py")]}}
    write_new(target / "protocol.json", protocol)
    receipt = read(root / "receipt.json"); by_hash = {r.get("sha256"): r for r in receipt.values()}
    results = []
    for old_result in read(root / "audit.json")["f1"]["pairs"]:
        pair = {"new": old_result["new"], "old": old_result["old"], "metadata_issues": []}
        docs, evidence = [], []
        for record, h in zip([pair["new"], pair["old"]], old_result.get("raw_hashes", [])):
            doc = read(root / "normalized" / (h + ".json"))
            raw = (root / by_hash[h]["file"]).read_bytes()
            identity = scoped_identity(raw, record)
            updated = deepcopy(doc); updated["dei"] = identity["dei"]
            docs.append(updated); evidence.append(identity)
        if len(docs) != 2:
            results.append({"new": pair["new"], "status": "unqualified", "issues": ["missing_original_source"]})
            continue
        # Retain original metadata rejection reasons, independently of parsing.
        selected_pair = next(r for r in read(root / "selections.json")["pairs"] if r["new"]["accessionNumber"] == pair["new"]["accessionNumber"])
        pair["metadata_issues"] = selected_pair["metadata_issues"]
        result = {"new": pair["new"], "old": pair["old"], **score_pair(pair, *docs),
                  "v1_status": old_result["status"], "v1_score": old_result["jaccard"],
                  "raw_hashes": old_result["raw_hashes"], "identity_evidence": evidence}
        if old_result["jaccard"] is not None and result["jaccard"] != old_result["jaccard"]:
            raise ValueError("Context repair changed a previously valid score")
        results.append(result)
    output = {"created_at": now(), "protocol_sha256": digest(target / "protocol.json"),
              "status_counts": dict(Counter(r["status"] for r in results)),
              "previously_valid_scores_unchanged": True, "return_labels_used": False,
              "investment_qualification": False, "pairs": results}
    write_new(target / "results.json", output)
    write_new(target / "manifest.json", {p.name: digest(p) for p in target.iterdir() if p.is_file()})
    print(json.dumps({k: v for k, v in output.items() if k != "pairs"}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, required=True)
    run(parser.parse_args().root)
