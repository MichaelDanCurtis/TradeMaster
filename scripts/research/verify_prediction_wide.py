"""Independent accounting audit of saved wide-universe portfolio results.

Replays saved scores without fitting models. Uses a fixed-point transaction-cost
equation instead of the simulation engine's bisection routine. Missing trade or
terminal prices stop the replay; transient missing marks are omitted explicitly.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np

MODELS = ("momentum_12_1", "ridge", "hgb", "equal_weight", "SPY", "cash")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def good(value):
    return value is not None and math.isfinite(value) and value > 0


def targets(row, model, symbols):
    if model == 'frozen_target':
        values = list(row['target_weights'])
        if len(values) != len(symbols)+1 or any(not math.isfinite(x) or x < 0 for x in values) or math.fsum(values)>1+1e-10:
            raise ValueError('Invalid independently replayed long-only target')
        return values
    w = [0.] * (len(symbols) + 1)
    eligible = row["eligible_symbols"]
    if model == "SPY":
        w[-1] = 1.
    elif model == "cash":
        pass
    elif model == "equal_weight":
        for s in eligible:
            w[symbols.index(s)] = 1 / len(eligible)
    else:
        scores = dict(zip(eligible, row["scores"][model]))
        chosen = sorted(eligible, key=lambda s: (-scores[s], symbols.index(s)))[:math.ceil(len(eligible) / 3)]
        for s in chosen:
            w[symbols.index(s)] = 1 / len(chosen)
    return w


def trade(values, cash, weights, rate):
    total = math.fsum(values) + cash
    after = total
    for _ in range(32):
        next_after = total - rate * math.fsum(abs(w * after - v) for w, v in zip(weights, values))
        if abs(next_after - after) <= 1e-15 * max(total, 1):
            after = next_after
            break
        after = next_after
    else:
        raise ArithmeticError("Independent transaction-cost equation did not converge")
    new_values = [w * after for w in weights]
    turnover = math.fsum(abs(a - b) for a, b in zip(new_values, values))
    fees = turnover * rate
    new_cash = total - math.fsum(new_values) - fees
    if new_cash < -1e-12:
        raise ArithmeticError("Negative independent cash")
    return new_values, max(0., new_cash), fees, turnover


def replay(panel, rows, model, rate):
    symbols = panel["symbols"]
    names = symbols + [panel["benchmark"]]
    first, last = rows[0]["entry_index"], rows[-1]["exit_index"]
    events = {r["entry_index"]: r for r in (rows[:1] if model == "SPY" else rows)}
    quantities = [0.] * len(names)
    cash, curve, ledger, gaps = 1., [], [], []
    max_security = max_issuer = max_sector = 0.
    min_effective = None

    def concentration(values, equity):
        nonlocal max_security, max_issuer, max_sector, min_effective
        weights = [v / equity for v in values]
        max_security = max(max_security, max(weights))
        if model not in ("SPY", "cash"):
            for field, label in (("issuers", "issuer"), ("sectors", "sector")):
                groups = {}
                for symbol, weight in zip(symbols, weights):
                    group = panel[field][symbol]
                    groups[group] = groups.get(group, 0.) + weight
                maximum = max(groups.values())
                if label == "issuer":
                    max_issuer = max(max_issuer, maximum)
                else:
                    max_sector = max(max_sector, maximum)
        sum_squared = math.fsum(w * w for w in weights)
        if sum_squared:
            effective = 1 / sum_squared
            min_effective = effective if min_effective is None else min(min_effective, effective)

    for t in range(first, last + 1):
        prices = [panel["series"][s]["open"][t] for s in names]
        target = [0.] * len(names) if t == last else targets(events[t], model, symbols) if t in events else None
        unresolved = [s for i, s in enumerate(names) if not good(prices[i]) and (quantities[i] > 0 or target is not None and target[i] > 0)]
        if unresolved and target is None:
            gaps.append({"date": panel["dates"][t], "index": t, "symbols": unresolved,
                         "action": "hold units unchanged; no valuation published; await next actual mark"})
            continue
        if unresolved:
            return {"state": "incomplete", "date": panel["dates"][t], "unresolved_symbols": unresolved,
                    "last_verified_equity": curve[-1]["equity"] if curve else 1.,
                    "held_units": {s: q for s, q in zip(names, quantities) if q > 0}, "curve": curve, "ledger": ledger}
        values = [q * p if q else 0. for q, p in zip(quantities, prices)]
        before = math.fsum(values) + cash
        concentration(values, before)
        if target is not None:
            values, cash, fees, turnover = trade(values, cash, target, rate)
            quantities = [v / p if v else 0. for v, p in zip(values, prices)]
            ledger.append({"index": t, "date": panel["dates"][t], "kind": "liquidation" if t == last else "rebalance",
                           "origin_index": events[t]["origin_index"] if t in events else None,
                           "equity_before": before, "equity_after": math.fsum(values) + cash,
                           "fees": fees, "traded_notional": turnover, "traded_fraction_of_equity": turnover / before,
                           "target_weights": target})
        equity = math.fsum(values) + cash
        concentration(values, equity)
        curve.append({"index": t, "date": panel["dates"][t], "equity": equity, "cash": cash})
    levels = np.array([1.] + [r["equity"] for r in curve])
    dr = levels[1:] / levels[:-1] - 1
    vol = float(np.std(dr, ddof=1) * math.sqrt(252))
    years = (date.fromisoformat(panel["dates"][last]) - date.fromisoformat(panel["dates"][first])).days / 365.25
    annual, prior = {}, 1.
    for year in sorted({r["date"][:4] for r in curve}):
        end = next(r["equity"] for r in reversed(curve) if r["date"].startswith(year))
        annual[year] = end / prior - 1
        prior = end
    marks = {r["index"]: r["equity"] for r in curve}
    trades = {r["index"]: r for r in ledger}
    periods = []
    for row in rows:
        a, b = row["entry_index"], row["exit_index"]
        start = trades[a]["equity_before"] if a in trades else marks[a]
        end = marks[b] if b == last else trades[b]["equity_before"] if b in trades else marks[b]
        periods.append(end / start - 1)
    return {"state": "complete", "net_return": float(levels[-1] - 1), "cagr": float(levels[-1] ** (1 / years) - 1),
            "max_drawdown": float(np.min(levels / np.maximum.accumulate(levels) - 1)),
            "annualized_volatility": vol if not gaps else None, "sharpe_zero_rate": float(dr.mean() * 252 / vol) if vol and not gaps else None,
            "valuation_gaps": gaps, "drawdown_scope": "observed actual opens only; missing marks omitted" if gaps else "daily actual opens",
            "annual_returns": annual, "max_single_security_weight": max_security,
            "max_issuer_weight": max_issuer if model not in ("SPY", "cash") else None,
            "max_sector_weight": max_sector if model not in ("SPY", "cash") else None,
            "minimum_effective_holdings": min_effective, "fees_fraction_initial_capital": math.fsum(r["fees"] for r in ledger),
            "two_sided_turnover_sum": math.fsum(r["traded_fraction_of_equity"] for r in ledger),
            "first_date": panel["dates"][first], "last_date": panel["dates"][last],
            "curve": curve, "ledger": ledger, "period_returns": periods, "daily_returns": dr.tolist()}


def ranks(values):
    order = sorted(range(len(values)), key=lambda i: values[i])
    out = [0.] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[start]] == values[order[end]]:
            end += 1
        for j in range(start, end):
            out[order[j]] = (start + 1 + end) / 2
        start = end
    return out


def interval(values):
    if len(values) < 2:
        return None
    values = np.asarray(values)
    n = len(values)
    starts = np.random.default_rng(59137).integers(0, n, size=(5000, math.ceil(n / 3)))
    indices = ((starts[:, :, None] + np.arange(3)) % n).reshape(5000, -1)[:, :n]
    means = values[indices].mean(axis=1)
    return {"mean": float(values.mean()), "interval95": np.quantile(means, [.025, .975]).tolist(),
            "block_origins": 3, "draws": 5000, "origin_count": n}


def verify(panel_path, prediction_path, report_path):
    panel = json.loads(panel_path.read_text())
    prediction = json.loads(prediction_path.read_text())
    saved = json.loads(report_path.read_text())
    rows, dates = prediction["rows"], panel["dates"]
    checks, errors = [], []
    maximum_difference = 0.

    def check(name, passed, detail=None):
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(name)

    def compare(a, b, path=""):
        nonlocal maximum_difference
        if isinstance(a, dict):
            for k, v in a.items():
                if k not in b:
                    raise AssertionError(path + "." + k + " missing")
                compare(v, b[k], path + "." + k)
        elif isinstance(a, list):
            if len(a) != len(b):
                raise AssertionError(path + " length")
            for i, (x, y) in enumerate(zip(a, b)):
                compare(x, y, path + f"[{i}]")
        elif isinstance(a, (float, int)) and not isinstance(a, bool):
            if b is None or not math.isfinite(b) or not math.isclose(a, b, rel_tol=1e-8, abs_tol=1e-10):
                raise AssertionError(f"{path}: {a} != {b}")
            maximum_difference = max(maximum_difference, abs(a - b))
        elif a != b:
            raise AssertionError(f"{path}: {a} != {b}")

    check("panel_hash", sha(panel_path) == prediction["metadata"]["panel_sha256"] == saved["inputs"]["panel_sha256"])
    check("predictions_hash", sha(prediction_path) == saved["inputs"]["predictions_sha256"])
    check("portfolio_runner_hash_current", sha(Path(__file__).with_name("prediction_wide_portfolios.py")) == saved["inputs"]["script_sha256"])
    check("accounting_primitives_hash_current", sha(Path(__file__).with_name("prediction_portfolios.py")) == saved["inputs"]["accounting_primitives_sha256"])
    check("ranking_runner_hash_current", sha(Path(__file__).with_name("prediction_wide_ranking.py")) == prediction["metadata"]["runner_sha256"])
    check("frozen_prediction_primitives_hash_current", sha(Path(__file__).with_name("prediction_ranking.py")) == prediction["metadata"]["frozen_primitives_sha256"])
    check("same_universe", prediction["metadata"]["symbols"] == panel["symbols"] and prediction["metadata"]["benchmark"] == panel["benchmark"])
    check("no_missing_forecast_origins", not prediction["failures"])
    check("five_year_endpoints", dates[rows[0]["entry_index"]] == "2021-09-07" and dates[rows[-1]["exit_index"]] == "2026-09-04")
    first = dates.index("2021-09-03")
    final = dates.index("2026-09-04")
    expected_origins = list(range(first, final - 1, 21))
    check("complete_fixed_origin_calendar", [r["origin_index"] for r in rows] == expected_origins)
    eligibility_errors, timing_errors = [], []
    mask = panel.get("membership")
    for j, row in enumerate(rows):
        t = row["origin_index"]
        eligible = []
        for i, s in enumerate(panel["symbols"]):
            series = panel["series"][s]
            if (mask is None or mask[t][i]) and all(good(v) for v in series["close"][t - 252:t + 1]) and all(good(v) for v in series["volume"][t - 252:t + 1]):
                eligible.append(s)
        if row["eligible_symbols"] != eligible:
            eligibility_errors.append(row["date"])
        if (row["date"] != dates[t] or row["entry_index"] != t + 1 or row["exit_index"] != min(t + 22, final)
                or row["truncated"] != (t + 22 > final) or row["last_training_exit_index"] > t
                or row["last_training_exit_index"] != row["last_training_origin"] + 22
                or j and rows[j - 1]["exit_index"] != row["entry_index"]):
            timing_errors.append(row["date"])
    check("eligibility_recomputed_from_past_only", not eligibility_errors, eligibility_errors)
    check("signal_entry_label_maturity_and_final_partial", not timing_errors, timing_errors)
    full = [not r["truncated"] for r in rows]
    check("reported_coverage_counts", saved["decision_count"] == len(rows) and saved["full_holding_count"] == sum(full)
          and saved["eligible_count_range"] == [min(len(r["eligible_symbols"]) for r in rows), max(len(r["eligible_symbols"]) for r in rows)]
          and saved["selected_count_range"] == [min(math.ceil(len(r["eligible_symbols"]) / 3) for r in rows), max(math.ceil(len(r["eligible_symbols"]) / 3) for r in rows)])
    completed = []
    for cost in (11, 22):
        independent = {m: replay(panel, rows, m, cost / 10000) for m in MODELS}
        for model, result in independent.items():
            if result["state"] == "complete":
                for control in ("equal_weight", "SPY"):
                    other = independent[control]
                    if other["state"] == "complete":
                        result["excess_net_return_vs_" + control] = result["net_return"] - other["net_return"]
                        result["paired_period_excess_vs_" + control] = interval([a - b for a, b, use in zip(result["period_returns"], other["period_returns"], full) if use])
                market = independent["SPY"]
                if market["state"] == "complete" and not result["valuation_gaps"] and not market["valuation_gaps"]:
                    r, m = np.array(result["daily_returns"]), np.array(market["daily_returns"])
                    centered_r, centered_m = r - r.mean(), m - m.mean()
                    result["beta_to_SPY"] = float(np.sum(centered_r * centered_m) / np.sum(centered_m ** 2))
                    result["correlation_to_SPY"] = float(np.sum(centered_r * centered_m) / math.sqrt(np.sum(centered_r ** 2) * np.sum(centered_m ** 2))) if r.std() else None
                if not math.isclose(math.prod(1 + v for v in result["period_returns"]), 1 + result["net_return"], rel_tol=1e-10):
                    raise ArithmeticError("Independent periods do not reconcile")
            try:
                compare(result, saved["costs"][str(cost)][model], f"{cost}.{model}")
                check(f"independent_accounting:{cost}:{model}", True, {"state": result["state"], "marks": len(result["curve"]), "transactions": len(result["ledger"])})
            except AssertionError as exc:
                check(f"independent_accounting:{cost}:{model}", False, str(exc))
            completed.append({"cost_bps": cost, "model": model, **{k: v for k, v in result.items() if k not in ("curve", "ledger", "period_returns", "daily_returns")}})
    for model in MODELS[:3]:
        scored, unresolved = [], []
        for row in rows:
            if row["truncated"]:
                continue
            prices = [(panel["series"][s]["open"][row["entry_index"]], panel["series"][s]["open"][row["exit_index"]]) for s in row["eligible_symbols"]]
            if any(not good(a) or not good(b) for a, b in prices):
                unresolved.append(row["origin_index"])
                continue
            x, y = np.array(ranks(row["scores"][model])), np.array(ranks([b / a - 1 for a, b in prices]))
            if not x.std() or not y.std():
                continue
            rho = float(np.mean((x - x.mean()) * (y - y.mean())) / (x.std() * y.std()))
            scored.append({"origin_index": row["origin_index"], "date": row["date"], "spearman": rho})
        accuracy = {"mean_spearman": float(np.mean([r["spearman"] for r in scored])) if scored else None,
                    "rows": scored, "unresolved_origins": unresolved, "excluded_final_partial": len(full) - sum(full)}
        try:
            compare(accuracy, saved["rank_accuracy"][model], "rank." + model)
            check("independent_rank_accuracy:" + model, True)
        except AssertionError as exc:
            check("independent_rank_accuracy:" + model, False, str(exc))
    return {"status": "passed" if not errors else "failed", "verified_at": datetime.now(timezone.utc).isoformat(),
            "verifier_sha256": sha(Path(__file__)), "checks": checks, "errors": errors,
            "inputs": {"panel_sha256": sha(panel_path), "prediction_sha256": sha(prediction_path), "portfolios_sha256": sha(report_path)},
            "maximum_absolute_numeric_difference": maximum_difference, "stock_count": len(panel["symbols"]),
            "decision_count": len(rows), "independent_results": completed,
            "limits": ["Independent portfolio accounting, timing, eligibility, costs, concentration, metrics and rank accuracy; learned scores were not independently refit.",
                       "Current surviving constituents, retrospectively adjusted prices and hypothetical adjusted-open fills remain limitations.",
                       "Transient missing held marks are omitted without trading or inventing prices; risk statistics require a complete daily valuation series. Missing trade/final prices still block exact terminal P&L.",
                       "Final September 4 valuation is the session OPEN, not its close; final partial hold is included in P&L and excluded from full-horizon rank/uncertainty calculations.",
                       "Inference is exploratory and not corrected for previous model searches."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--portfolios", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.panel, args.predictions, args.portfolios)
    with args.output.open("x") as out:
        json.dump(result, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({k: result[k] for k in ("status", "errors", "stock_count", "decision_count", "maximum_absolute_numeric_difference")}))
    if result["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
