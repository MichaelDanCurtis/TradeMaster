"""Independent artifact and set-arithmetic checks for the original-filing pilot."""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify(root):
    load = lambda name: json.loads((root / name).read_text())
    manifest, protocol, audit = load("manifest.json"), load("protocol.json"), load("audit.json")
    checked = 0
    for name, expected in manifest["files"].items():
        if sha(root / name) != expected:
            raise ValueError("Artifact hash mismatch: " + name)
        checked += 1
    if sha(root / "protocol.json") != load("protocol-lock.json")["sha256"]:
        raise ValueError("Protocol lock mismatch")
    if sha(root / "selections.json") != load("selection-lock.json")["sha256"]:
        raise ValueError("Selection lock mismatch")
    for filename, expected in protocol["code_hashes"].items():
        if sha(Path(filename)) != expected:
            raise ValueError("Frozen code mismatch")
    universe = Path(protocol["source_universe"])
    if sha(universe) != protocol["source_universe_sha256"]:
        raise ValueError("Source universe mismatch")
    receipt = load("receipt.json")
    for entry in receipt.values():
        if entry["status"] == "captured" and sha(root / entry["file"]) != entry["sha256"]:
            raise ValueError("Receipt hash mismatch")
    pairs_checked, valid_scores = 0, []
    seen = set()
    for pair in audit["f1"]["pairs"]:
        accession = pair["new"]["accessionNumber"]
        if accession in seen:
            raise ValueError("Duplicate scored filing")
        seen.add(accession)
        if pair["status"] != "structurally_validated":
            if pair["jaccard"] is not None:
                raise ValueError("Unqualified pair carries a score")
            continue
        new, old = pair["new"], pair["old"]
        if new["cik"] != old["cik"] or new["form"] != old["form"] or new["form"] not in {"10-K", "10-Q"}:
            raise ValueError("Pair identity or form mismatch")
        days = (date.fromisoformat(new["reportDate"]) - date.fromisoformat(old["reportDate"])).days
        if not 350 <= days <= 380 or old["filingDate"] >= new["filingDate"]:
            raise ValueError("Nonhistorical pair")
        documents = [load("normalized/" + h + ".json") for h in pair["raw_hashes"]]
        left, right = (set(d["tokens"]) for d in documents)
        # Independent equivalent formula rather than calling the production scorer.
        intersection = len(left) + len(right) - len(left.union(right))
        expected = intersection / len(left.union(right))
        if abs(pair["jaccard"] - expected) > 1e-15:
            raise ValueError("Jaccard arithmetic mismatch")
        for d in documents:
            token_hash = hashlib.sha256("\n".join(sorted(d["tokens"])).encode()).hexdigest()
            if token_hash != d["tokens_sha256"] or len(set(d["tokens"])) != d["distinct_tokens"]:
                raise ValueError("Normalized token mismatch")
        if documents[0]["dei"]["documentfiscalperiodfocus"] != documents[1]["dei"]["documentfiscalperiodfocus"]:
            raise ValueError("Fiscal period mismatch")
        if int(documents[0]["dei"]["documentfiscalyearfocus"][0]) != int(documents[1]["dei"]["documentfiscalyearfocus"][0]) + 1:
            raise ValueError("Fiscal year mismatch")
        pairs_checked += 1; valid_scores.append(expected)
    if audit["investment_status"] != "not_qualified_for_SPY_comparison":
        raise ValueError("Pilot incorrectly promoted to investment evidence")
    return {"status": "passed", "artifacts_checked": checked, "pair_scores_independently_checked": pairs_checked,
            "source_files": len(receipt), "investment_qualification": False,
            "limits": "Verifies hashes, fiscal identity and token-set arithmetic; not independent semantic parsing or historical universe coverage",
            "manifest_sha256": sha(root / "manifest.json")}


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--root", type=Path, required=True)
    a = parser.parse_args(); result = verify(a.root)
    with (a.root / "verification.json").open("x") as handle:
        json.dump(result, handle, indent=2); handle.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
