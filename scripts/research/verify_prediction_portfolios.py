"""Independent interval-return/cost and manual-rank verification of saved portfolios.

Does not import the evaluator, its normalizer, simulator, rebalance solver, or
scipy's rank correlation. It reads saved signals and prices, never fits models.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_rows(root, cohort, panel):
    payload = json.loads((root / cohort / "predictions.json").read_bytes())
    names = panel["symbols"]
    if cohort == "reversal":
        assert payload["symbols"] == names and payload["benchmark"] == panel["benchmark"]
        canonical = json.dumps(panel, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        assert payload["panel_sha256"] == hashlib.sha256(canonical).hexdigest()
        return payload["rows"]
    assert payload["metadata"]["symbols"] == names
    assert payload["metadata"]["benchmark"] == panel["benchmark"]
    assert payload["metadata"]["panel_sha256"] == digest(root / "panel.json")
    records = {}
    timing = {}
    for row in payload["predictions"]:
        t = row["origin_index"]
        key = (t, row["model"], row["symbol"])
        assert key not in records
        records[key] = row["score"]
        pair = (row["entry_index"], row["exit_index"])
        assert t not in timing or timing[t] == pair
        timing[t] = pair
    models = sorted({key[1] for key in records})
    return [{"origin_index": t, "entry_index": timing[t][0], "exit_index": timing[t][1],
             "scores": {m: [records[t, m, name] for name in names] for m in models}}
            for t in sorted(timing)]


def ranks(values):
    """One-based midranks without scipy; ties receive the mean occupied rank."""
    values = list(values)
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = np.zeros(len(values))
    left = 0
    while left < len(values):
        right = left + 1
        while right < len(values) and values[order[right]] == values[order[left]]:
            right += 1
        for i in order[left:right]:
            out[i] = (left + 1 + right) / 2
        left = right
    return out


def correlation(scores, outcomes):
    x = ranks(scores); y = ranks(outcomes)
    x -= x.mean(); y -= y.mean()
    divisor = float(np.linalg.norm(x) * np.linalg.norm(y))
    assert divisor > 0
    return float((x @ y) / divisor)


def weights_for(model, scores, n):
    weights = np.zeros(n + 1)
    if model == "cash":
        return weights
    if model == "SPY":
        weights[-1] = 1
    elif model == "equal_weight":
        weights[:n] = 1/n
    else:
        selected = sorted(enumerate(scores), key=lambda pair: (-pair[1], pair[0]))[:math.ceil(n/3)]
        for i, _ in selected:
            weights[i] = 1/len(selected)
    return weights


def reference_portfolio(prices, rows, model, rate):
    """Carry asset values between interval boundaries; solve fees by contraction.

    f = rate * sum(abs(w*(equity-f)-old_values)). The contraction factor is
    at most rate for unlevered weights. This differs from the evaluator's
    equity bisection, daily share accounting, and ledger partitioning.
    """
    n = prices.shape[1]-1
    values = np.zeros(n+1)
    cash = 1.0
    total_fees = 0.0
    turnover = 0.0
    period_returns = []
    for period, row in enumerate(rows):
        before = float(values.sum()+cash)
        if model != "SPY" or period == 0:
            weights = weights_for(model, row["scores"].get(model), n)
            fee = 0.0
            for _ in range(100):
                updated = rate * float(np.abs(weights*(before-fee)-values).sum())
                if abs(updated-fee) <= 1e-15 * max(1.0, before):
                    fee = updated
                    break
                fee = updated
            else:
                raise ArithmeticError("Independent cost iteration failed")
            targets = weights*(before-fee)
            traded = float(np.abs(targets-values).sum())
            assert abs(fee-rate*traded) < 1e-12
            cash = before-fee-float(targets.sum())
            assert cash >= -1e-12
            values = targets
            total_fees += fee
            turnover += traded/before
        values = values*(prices[row["exit_index"]]/prices[row["entry_index"]])
        if period == len(rows)-1:
            liquidation_before = float(values.sum()+cash)
            liquidation_traded = float(values.sum())
            fee = rate*liquidation_traded
            turnover += liquidation_traded/liquidation_before
            total_fees += fee
            cash += liquidation_traded-fee
            values[:] = 0
        ending = float(values.sum()+cash)
        period_returns.append(ending/before-1)
    return {"net_return": float(cash-1), "fees_fraction_initial_capital": total_fees,
            "two_sided_turnover_sum": turnover, "period_returns": period_returns}


def verify(root):
    panel = json.loads((root/"panel.json").read_bytes())
    report_path = root/"portfolios"/"portfolios.json"
    report = json.loads(report_path.read_bytes())
    assert report["panel_sha256"] == digest(root/"panel.json")
    assert report["protocol_sha256"] == digest(root/"protocol.json")
    prices = np.array([panel["series"][s]["open"] for s in panel["symbols"]+[panel["benchmark"]]]).T
    checks = []
    ic_checks = []
    for cohort, result in report["cohorts"].items():
        assert report["input_prediction_hashes"][cohort] == digest(root/cohort/"predictions.json")
        rows = load_rows(root, cohort, panel)
        horizon = 21 if cohort == "ranking" else 5
        assert all(r["entry_index"] == r["origin_index"]+1 and r["exit_index"] == r["entry_index"]+horizon for r in rows)
        assert all(a["exit_index"] == b["entry_index"] for a, b in zip(rows, rows[1:]))
        assert result["origin_count"] == len(rows)
        for model, item in result["rank_accuracy"].items():
            expected = [correlation(r["scores"][model], prices[r["exit_index"], :-1]/prices[r["entry_index"], :-1]-1) for r in rows]
            actual = [r["spearman"] for r in item["rows"]]
            assert [r["date"] for r in item["rows"]] == [panel["dates"][r["origin_index"]] for r in rows]
            assert np.allclose(expected, actual, atol=1e-12, rtol=0)
            assert abs(float(np.mean(expected))-item["mean_spearman"]) < 1e-12
            assert item["dates_positive"] == sum(v > 0 for v in expected)
            ic_checks.append({"cohort": cohort, "model": model, "origin_count": len(rows),
                              "max_abs_error": float(np.max(np.abs(np.array(expected)-actual))), "passed": True})
        for bps, portfolios in result["costs"].items():
            references = {model: reference_portfolio(prices, rows, model, int(bps)/10000) for model in portfolios}
            base = references["equal_weight"]
            for model, actual in portfolios.items():
                expected = references[model]
                errors = {}
                for metric in ("net_return", "fees_fraction_initial_capital", "two_sided_turnover_sum"):
                    errors[metric] = abs(expected[metric]-actual[metric])
                    assert math.isclose(expected[metric], actual[metric], abs_tol=1e-10, rel_tol=1e-10), (cohort, bps, model, metric, errors[metric])
                error = float(np.max(np.abs(np.array(expected["period_returns"])-actual["period_returns"])))
                assert error < 1e-10
                errors["max_period_return"] = error
                paired = np.array(expected["period_returns"])-base["period_returns"]
                assert abs(float(paired.mean())-actual["paired_period_excess"]["mean"]) < 1e-10
                assert math.isclose(expected["net_return"]-base["net_return"], actual["excess_net_return_vs_equal_weight"], abs_tol=1e-10, rel_tol=1e-10)
                assert math.isclose(expected["net_return"]-references["SPY"]["net_return"], actual["excess_net_return_vs_SPY"], abs_tol=1e-10, rel_tol=1e-10)
                checks.append({"cohort": cohort, "model": model, "cost_bps_per_side": int(bps),
                               "reference_final_equity": expected["net_return"]+1, "absolute_errors": errors, "passed": True})
    return {"state": "passed", "checked_at": datetime.now(timezone.utc).isoformat(),
            "method": "Independent interval asset-value recurrence; fixed-point fee solve; manual midrank/Pearson Spearman; no evaluator imports",
            "tolerance": "1e-10 absolute/relative financial comparisons; 1e-12 absolute rank correlation",
            "portfolio_cost_cases": len(checks), "rank_model_cases": len(ic_checks),
            "rank_origin_checks": sum(r["origin_count"] for r in ic_checks),
            "portfolio_checks": checks, "rank_checks": ic_checks,
            "report_sha256": digest(report_path), "panel_sha256": digest(root/"panel.json"),
            "verifier_sha256": digest(Path(__file__)),
            "scope": "Verifies recorded signal-to-portfolio arithmetic, timing, fees and ranking scores; does not establish source vintage quality or live profitability"}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", type=Path, required=True)
    args = ap.parse_args()
    result = verify(args.root)
    output = args.root/"portfolios"/"verification.json"
    with output.open("x") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write("\n")
    print(json.dumps({key: result[key] for key in ("state", "portfolio_cost_cases", "rank_model_cases", "rank_origin_checks")}, indent=2))


if __name__ == "__main__":
    main()
