"""Verify all frozen selections against past-only data and portfolio limits."""
import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np

from scripts.research.insider_quality_final import load_inputs, verify_lock, weekly_decision, write_new
from scripts.research.disclosure_signals import sha


def verify(root):
    verify_lock(root)
    protocol, panel, events = load_inputs(root)
    compiled = json.loads((root / "compiled-quality.json").read_text())
    audit = json.loads((root / "decision-evidence.json").read_text())
    variants = ["risk_insider", "risk_insider_coverage_matched", "risk_insider_quality", "SPY_risk12"]
    frozen = {v: json.loads((root / (v + "-targets.json")).read_text()) for v in variants}
    names, dates = panel["symbols"], panel["dates"]
    checks, exposed, missing = [], [], Counter()
    for index, record in enumerate(audit):
        t = dates.index(record["date"])
        members = [s for s, active in zip(names, panel["membership"][t - 1]) if active]
        retired = [e["old"] for e in panel["valuation_only_reconciliation"]["events"]
                   if e["date"] <= dates[t - 1] and e["old"] not in [x["symbol"] for x in e["successors"]]]
        past_events = [e for e in events if e["disclosed"] < dates[t]]
        past_facts = {s: {m: [r for r in rows if r["filed"] < dates[t - 1]] for m, rows in facts.items()}
                      for s, facts in compiled.items() if s in record["ranked_candidates"]}
        past_prices = {s: panel["series"][s]["close"][:t] for s in record["ranked_candidates"] + ["SPY"]}
        decision, evidence = weekly_decision(past_events, dates[:t + 1], t, members, retired,
                                              past_facts, past_prices, panel["sectors"])
        if evidence != record:
            raise ValueError("Past-only evidence differs from frozen decision")
        for variant in variants:
            expected = frozen[variant][index]
            if any(expected[k] != decision[variant][k] for k in ["weights_by_symbol", "risk"]):
                raise ValueError("Past-only weights differ from frozen decision")
            weights = expected["weights_by_symbol"]
            np.testing.assert_allclose(expected["target_weights"], [weights.get(s, 0.) for s in names + ["SPY"]], rtol=0, atol=0)
            if not all(np.isfinite(w) and w >= 0 for w in weights.values()) or sum(weights.values()) > 1 + 1e-12:
                raise ValueError("Invalid target exposure")
            if variant != "SPY_risk12":
                if any(w > .05 + 1e-12 for w in weights.values()) or len(weights) > 20:
                    raise ValueError("Position limit exceeded")
                sectors = Counter()
                for s, w in weights.items():
                    sectors[panel["sectors"].get(s) or "Unknown historical sector"] += w
                    if s not in members or s in retired:
                        raise ValueError("Ineligible historical member")
                if any(w > .2 + 1e-12 for w in sectors.values()):
                    raise ValueError("Sector limit exceeded")
            risk = expected["risk"]["estimated_volatility"]
            if risk is not None and risk > .12 + 1e-12:
                raise ValueError("Estimated risk limit exceeded")
            if variant == "risk_insider_quality":
                if any(record["quality"][s]["state"] != "pass" for s in weights):
                    raise ValueError("Nonpassing quality selected")
            if variant == "risk_insider_coverage_matched":
                if any(record["quality"][s]["state"] == "unknown" for s in weights):
                    raise ValueError("Unknown quality coverage selected")
            exposed.append({"date": record["date"], "variant": variant, "target_exposure": sum(weights.values()),
                            "names": len(weights), "estimated_volatility": risk})
        missing.update(q.get("reason", q["state"]) for q in record["quality"].values())
        checks.append({"date": record["date"], "variants_replayed": len(variants), "passed": True})
        if len(checks) % 100 == 0:
            print("Verified past-only weeks", len(checks), flush=True)
    forward = Path('.research-artifacts/prediction-forward-2026-09-07/protocol.json')
    fp = json.loads(forward.read_text())
    for path, expected in fp["code_sha256"].items():
        if sha(path) != expected:
            raise ValueError("Existing forward-study dependency changed")
    write_new(root / "causal-verification.json", {"targets_lock_sha256": sha(root / "targets-lock.json"),
              "weekly_replays": checks, "portfolio_replays": len(checks) * len(variants),
              "target_exposures": exposed, "quality_states_and_gaps": dict(missing),
              "forward_study_dependencies_unchanged": len(fp["code_sha256"]),
              "limits_scope": "Targets at rebalances; between-rebalance drift and realized volatility are not capped."})
    print(json.dumps({"weekly_replays": len(checks), "portfolio_replays": len(checks) * len(variants),
                      "forward_dependencies_unchanged": len(fp["code_sha256"])}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    verify(parser.parse_args().root)
