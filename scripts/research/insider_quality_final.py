"""One fixed insider/quality hypothesis, causal controls and costed valuation.

Research only. No network, model fitting, broker or execution integration.
"""
from __future__ import annotations

import argparse
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import math
from pathlib import Path
import re

import numpy as np

from scripts.research.disclosure_signals import sha, select, targets as original_targets
from scripts.research.prediction_fundamentals import compile_facts


def write_new(path, value):
    with Path(path).open("x") as handle:
        json.dump(value, handle, indent=2, allow_nan=False)


def quality_at(compiled, cutoff):
    """One complete annual vintage; never combine different accession statements."""
    if not compiled:
        return {"state": "unknown", "reason": "missing_issuer_or_SEC_facts"}
    oldest = (date.fromisoformat(cutoff) - timedelta(days=550)).isoformat()
    anchors = {(r["end"], r["filed"], r["accession"], r["start"])
               for r in compiled.get("ocf", []) if oldest <= r["end"] <= cutoff
               and r["filed"] < cutoff and re.fullmatch(r"\d{10}-\d{2}-\d{6}", r.get("accession") or "")}
    for end, filed, accession, start in sorted(anchors, reverse=True):
        values, evidence = {}, {}
        valid = True
        for metric in ["income", "ocf", "capex", "assets"]:
            matches = [r for r in compiled.get(metric, [])
                       if r["end"] == end and r["filed"] == filed and r["accession"] == accession
                       and (metric == "assets" or r["start"] == start)]
            if not matches:
                valid = False
                break
            priority = min(r["priority"] for r in matches)
            matches = [r for r in matches if r["priority"] == priority]
            if len({r["value"] for r in matches}) != 1:
                # A conflicting latest complete vintage cannot be replaced by a
                # convenient earlier positive observation.
                return {"state": "unknown", "reason": "conflicting_vintage", "accession": accession}
            record = matches[0]
            if not math.isfinite(record["value"]):
                valid = False
                break
            values[metric] = record["value"]
            evidence[metric] = {k: record[k] for k in ["value", "tag", "start", "end", "filed", "accession"]}
        if not valid:
            continue
        if values["assets"] <= 0 or values["capex"] < 0:
            return {"state": "unknown", "reason": "invalid_asset_or_capex_sign", "accession": accession}
        fcf = values["ocf"] - values["capex"]
        checks = {"positive_income": values["income"] > 0,
                  "positive_operating_cash_flow": values["ocf"] > 0, "positive_free_cash_flow": fcf > 0}
        return {"state": "pass" if all(checks.values()) else "fail", "checks": checks,
                "values": {**values, "free_cash_flow": fcf}, "end": end, "filed": filed,
                "accession": accession, "evidence": evidence}
    return {"state": "unknown", "reason": "no_recent_complete_annual_vintage"}


def trailing_returns(close_history):
    """Caller supplies only history through the prior session close."""
    prices = np.asarray(close_history[-64:], dtype=float)
    if prices.shape != (64,) or not np.isfinite(prices).all() or (prices <= 0).any():
        return None
    return prices[1:] / prices[:-1] - 1


def controlled_weights(ranked, sectors, returns, *, benchmark=False):
    chosen, counts = [], Counter()
    for symbol in ranked:
        r = returns.get(symbol)
        if r is None:
            continue
        arr = np.asarray(r, dtype=float)
        if arr.shape != (63,) or not np.isfinite(arr).all():
            continue
        bucket = sectors.get(symbol) or "Unknown historical sector"
        if not benchmark and counts[bucket] >= 4:
            continue
        chosen.append(symbol)
        counts[bucket] += 1
        if len(chosen) == (1 if benchmark else 20):
            break
    if not chosen:
        return {}, {"selected": [], "unscaled_volatility": None, "scale": 0., "estimated_volatility": None,
                    "cash_weight": 1., "sector_weights": {}}
    base = np.full(len(chosen), 1. if benchmark else .05)
    matrix = np.column_stack([returns[s] for s in chosen])
    # Variance of aligned weighted returns equals w.T @ sample_cov @ w.
    volatility = float(np.std(matrix @ base, ddof=1) * np.sqrt(252))
    scale = min(1., .12 / volatility) if volatility > 0 else 1.
    weights = {s: float(w * scale) for s, w in zip(chosen, base)}
    groups = defaultdict(float)
    for symbol, weight in weights.items():
        groups[sectors.get(symbol) or "Unknown historical sector"] += weight
    return weights, {"selected": chosen, "unscaled_volatility": volatility, "scale": scale,
                     "estimated_volatility": volatility * scale, "cash_weight": 1. - sum(weights.values()),
                     "sector_weights": dict(groups)}


def weekly_decision(events, dates, t, members, retired, compiled, history, sectors):
    selection = select(events, dates, t, members, retired=retired)
    ranked = sorted(selection["scores"], key=lambda s: (-float(selection["scores"][s]), s))
    quality = {s: quality_at(compiled.get(s), dates[t - 1]) for s in ranked}
    returns = {s: trailing_returns(history[s]) for s in ranked + ["SPY"]}
    variants = {"risk_insider": ranked,
                "risk_insider_coverage_matched": [s for s in ranked if quality[s]["state"] != "unknown"],
                "risk_insider_quality": [s for s in ranked if quality[s]["state"] == "pass"],
                "SPY_risk12": ["SPY"]}
    result = {}
    for name, candidates in variants.items():
        weights, risk = controlled_weights(candidates, sectors, returns, benchmark=name == "SPY_risk12")
        result[name] = {"weights_by_symbol": weights, "risk": risk}
    return result, {"date": dates[t], "cutoff": dates[t - 1], "ranked_candidates": ranked,
                    "insider_scores": selection["scores"], "quality": quality,
                    "risk_unavailable": [s for s in returns if returns[s] is None]}


def load_inputs(root):
    protocol = json.loads((root / "protocol.json").read_text())
    for filename, expected in protocol["input_hashes"].items():
        if sha(filename) != expected:
            raise ValueError("Frozen source changed")
    panel = json.loads(Path(protocol["panel"]).read_text())
    events = json.loads(Path(protocol["events"]).read_text())
    return protocol, panel, events


def prepare(root):
    if (root / "targets-lock.json").exists():
        raise ValueError("This experiment is already frozen")
    protocol, panel, events = load_inputs(root)
    sec = Path(protocol["sec_root"])
    receipt = json.loads((sec / "receipt.json").read_text())
    compiled, source_hashes, coverage = {}, {}, []
    candidates = sorted({e["symbol"] for e in events if "2018-10-01" <= e["disclosed"] < protocol["end"]} & set(panel["symbols"]))
    cache = {}
    for s in candidates:
        cik = panel["issuers"].get(s, "")
        name = cik + ".json"
        if not re.fullmatch(r"\d{10}", cik) or name not in receipt["responses"]:
            coverage.append({"symbol": s, "state": "missing_historical_issuer_mapping_or_SEC_capture"})
            continue
        path = sec / name
        expected = receipt["responses"][name]["sha256"]
        if sha(path) != expected:
            raise ValueError("SEC source changed")
        source_hashes[str(path)] = expected
        if cik not in cache:
            payload = json.loads(path.read_text())
            if str(payload["cik"]).zfill(10) != cik:
                raise ValueError("Issuer CIK mismatch")
            cache[cik] = compile_facts(payload)
        compiled[s] = cache[cik]
        coverage.append({"symbol": s, "state": "captured", "cik": cik, "sha256": expected})
    write_new(root / "compiled-quality.json", compiled)
    write_new(root / "SEC-coverage.json", coverage)
    names, dates = panel["symbols"], panel["dates"]
    first, last = bisect_left(dates, protocol["start"]), bisect_left(dates, protocol["end"])
    if dates[first] != protocol["start"] or dates[last] != protocol["end"]:
        raise ValueError("Exact requested endpoints not covered")
    data = {name: [] for name in protocol["variants"]}
    data["original_insider"] = original_targets(panel, events, protocol["start"], protocol["end"], 0)
    audit, previous_week = [], None
    for t in range(first, last):
        week = date.fromisoformat(dates[t]).isocalendar()[:2]
        if week == previous_week:
            continue
        previous_week = week
        members = [s for s, active in zip(names, panel["membership"][t - 1]) if active]
        retired = [e["old"] for e in panel["valuation_only_reconciliation"]["events"]
                   if e["date"] <= dates[t - 1] and e["old"] not in [x["symbol"] for x in e["successors"]]]
        history = {s: panel["series"][s]["close"][:t] for s in names + ["SPY"]}
        decisions, record = weekly_decision(events, dates, t, members, retired, compiled, history, panel["sectors"])
        audit.append(record)
        for variant, decision in decisions.items():
            weights = decision["weights_by_symbol"]
            data[variant].append({"date": dates[t], "entry_index": t, "exit_index": last,
                                  "target_weights": [weights.get(s, 0.) for s in names + ["SPY"]], **decision})
        if len(audit) % 50 == 0:
            print("Frozen weekly decisions", len(audit), flush=True)
    data["SPY_buy_hold"] = [{"date": dates[first], "entry_index": first, "exit_index": last,
                             "target_weights": [0.] * len(names) + [1.]}]
    for variant, rows in data.items():
        write_new(root / (variant + "-targets.json"), rows)
    write_new(root / "decision-evidence.json", audit)
    code = [__file__, "scripts/research/disclosure_signals.py", "scripts/research/prediction_fundamentals.py",
            "scripts/research/prediction_event_accounting.py", "scripts/research/prediction_portfolios.py",
            "scripts/research/verify_prediction_wide.py", "scripts/research/evaluate_astra_capsules.py"]
    files = [root / "protocol.json", root / "compiled-quality.json", root / "SEC-coverage.json", root / "decision-evidence.json"]
    files += [root / (v + "-targets.json") for v in data]
    write_new(root / "targets-lock.json", {"frozen_at": datetime.now(timezone.utc).isoformat(),
              "files": {p.name: sha(p) for p in files}, "sec_sources": source_hashes,
              "code_sha256": {str(Path(p)): sha(p) for p in code}})
    print(json.dumps({"weekly_decisions": len(audit), "signal_symbols": len(candidates),
                      "SEC_mapped_symbols": len(compiled), "target_files": len(data)}), flush=True)


def verify_lock(root):
    lock = json.loads((root / "targets-lock.json").read_text())
    for filename, expected in lock["files"].items():
        if sha(root / filename) != expected:
            raise ValueError("Frozen selections changed")
    for filename, expected in {**lock["sec_sources"], **lock["code_sha256"]}.items():
        if sha(filename) != expected:
            raise ValueError("Frozen code or SEC inputs changed")


def period_return(result, start, end):
    curve = result.get("curve", [])
    inside = [r for r in curve if start <= r["date"] < end]
    if not inside:
        return None
    previous = [r for r in curve if r["date"] < start]
    return inside[-1]["equity"] / (previous[-1]["equity"] if previous else 1.) - 1


def score(root):
    from scripts.research.prediction_event_accounting import simulate_events
    from scripts.research.evaluate_astra_capsules import compare_recursive
    verify_lock(root)
    protocol, panel, _ = load_inputs(root)
    result, checks = {}, 0
    for variant in protocol["variants"]:
        rows = json.loads((root / (variant + "-targets.json")).read_text())
        result[variant] = {}
        for bps in protocol["cost_bps_per_side"]:
            a = simulate_events(panel, rows, panel["valuation_only_reconciliation"]["events"], bps / 10000)
            b = simulate_events(panel, rows, panel["valuation_only_reconciliation"]["events"], bps / 10000, audit=True)
            compare_recursive(a, b)
            checks += 1
            a["period_returns"] = {label: period_return(a, lo, hi) for label, lo, hi in [
                ("2019-2021", "2019-01-01", "2022-01-01"),
                ("2022-2023", "2022-01-01", "2024-01-01"),
                ("2024-2025", "2024-01-01", "2026-01-01")]}
            result[variant][str(bps)] = a
            print(variant, bps, a["state"], a.get("cagr"), a.get("max_drawdown"), a.get("date"), a.get("unresolved_symbols"), flush=True)
    verdict = {}
    for bps in protocol["cost_bps_per_side"]:
        q, s, baseline = [result[v][str(bps)] for v in ["risk_insider_quality", "SPY_risk12", "risk_insider_coverage_matched"]]
        complete = all(x["state"] == "complete" and not x["valuation_gaps"] for x in [q, s, baseline])
        gates = {"complete": complete}
        if complete:
            gates.update(cagr=all(q["cagr"] > x["cagr"] for x in [s, baseline]),
                         sharpe=all(q["sharpe_zero_rate"] is not None and x["sharpe_zero_rate"] is not None
                                    and q["sharpe_zero_rate"] >= x["sharpe_zero_rate"] + .10 for x in [s, baseline]),
                         drawdown=q["max_drawdown"] >= s["max_drawdown"] - .02,
                         late_period=q["period_returns"]["2024-2025"] > s["period_returns"]["2024-2025"])
        verdict[str(bps)] = {"gates": gates, "passes": complete and all(gates.values())}
    write_new(root / "results.json", {"portfolios": result, "verdict": verdict, "two_cost_solver_replays": checks,
              "overall_pass": all(v["passes"] for v in verdict.values()), "targets_lock_sha256": sha(root / "targets-lock.json")})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["prepare", "score"])
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    (prepare if args.stage == "prepare" else score)(args.root)
