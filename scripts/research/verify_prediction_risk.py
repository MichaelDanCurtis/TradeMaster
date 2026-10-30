"""Independent risk score reconstruction and paired date-block uncertainty.

Reads the saved panel and forecasts. Does not import, fit, or change risk models.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def key(row):
    return row["symbol"], row["origin_date"], row["horizon"], row["method"]


def verify(panel_path, run):
    panel = json.loads(panel_path.read_text())
    manifest = json.loads((run / "protocol.json").read_text())
    receipt = json.loads((run / "forecast-receipt.json").read_text())
    report = json.loads((run / "report.json").read_text())
    forecasts = [json.loads(line) for line in (run / "forecasts.jsonl").read_text().splitlines()]
    saved_scores = [json.loads(line) for line in (run / "scores.jsonl").read_text().splitlines()]
    checks, errors = [], []

    def check(name, value, detail=None):
        checks.append({"check": name, "passed": bool(value), "detail": detail})
        if not value:
            errors.append(name)

    check("panel_hash", sha(panel_path) == manifest["panel_sha256"] == report["panel_sha256"])
    check("protocol_hash", canonical_hash(manifest["protocol"]) == manifest["protocol_sha256"] == report["protocol_sha256"])
    check("forecast_hash", sha(run / "forecasts.jsonl") == receipt["forecast_sha256"] == report["forecast_sha256"])
    check("forecast_saved_before_scoring_recorded_times", datetime.fromisoformat(receipt["forecasts_frozen_at"]) < datetime.fromisoformat(report["scored_at"]))
    check("row_count_receipt", len(forecasts) == receipt["rows"] == report["rows"] == len(saved_scores))
    check("forecasts_do_not_contain_outcomes", all(not ({"target_variance", "qlike", "mse"} & row.keys()) for row in forecasts))
    symbols = panel["symbols"] + [panel["benchmark"]]
    dates = panel["dates"]
    anchor = next(i for i, d in enumerate(dates) if d >= "2023-01-03")
    origins = [t for t in range(anchor, len(dates), 21) if t >= 504 and t + 22 < len(dates)]
    expected_keys = {(s, dates[t], h, m) for t in origins for s in symbols for h in (5, 20) for m in ("trailing20", "ewma094", "garch11")}
    check("exact_frozen_forecast_population", {key(r) for r in forecasts} == expected_keys and len(forecasts) == len(expected_keys))
    check("score_population", {key(r) for r in saved_scores} == expected_keys and len(saved_scores) == len(expected_keys))
    check("origin_calendar", [dates[t] for t in origins] == manifest["origin_dates"])
    saved = {key(row): row for row in saved_scores}
    reconstructed = {}
    max_diff = {"forecast_mean": 0.0, "target": 0.0, "qlike": 0.0, "mse": 0.0, "trailing_or_ewma": 0.0}
    numeric_errors = []
    metadata_errors = []
    failure_errors = []
    for row in forecasts:
        s, d, h, method = key(row)
        t = dates.index(d)
        prices = panel["series"][s]["close"]
        old = saved[key(row)]
        if row["origin_index"] != t or row["input_return_count"] != 504 or row["last_input_date"] != d or row["first_input_close_date"] != dates[t - 504]:
            metadata_errors.append(key(row))
        if row["input_close_sha256"] != canonical_hash(prices[t - 504:t + 1]):
            metadata_errors.append(key(row))
        if any(old.get(k) != value for k, value in row.items()):
            metadata_errors.append(key(row))
        # Different numerical expression from the runner's diff(log(prices)).
        future_returns = [math.log(prices[j] / prices[j - 1]) for j in range(t + 1, t + h + 1)]
        y = math.fsum(value * value for value in future_returns) / h
        max_diff["target"] = max(max_diff["target"], abs(y - old["target_variance"]))
        if not math.isclose(y, old["target_variance"], rel_tol=1e-10, abs_tol=1e-15):
            numeric_errors.append({"key": key(row), "field": "target"})
        if old["target_first_date"] != dates[t + 1] or old["target_last_date"] != dates[t + h]:
            metadata_errors.append(key(row))
        new = {"target": y, "state": row["state"]}
        if row["state"] == "completed":
            values = row["daily_variance"]
            if len(values) != h or any(not math.isfinite(v) or v < 0 for v in values):
                numeric_errors.append({"key": key(row), "field": "daily_variance"})
            prediction = math.fsum(values) / h
            max_diff["forecast_mean"] = max(max_diff["forecast_mean"], abs(prediction - row["forecast_variance"]))
            if not math.isclose(prediction, row["forecast_variance"], rel_tol=1e-12, abs_tol=1e-15):
                numeric_errors.append({"key": key(row), "field": "forecast_mean"})
            safe = max(prediction, 1e-12)
            new.update(prediction=prediction, qlike=math.log(safe) + y / safe, mse=(y - prediction) ** 2)
            for field in ("qlike", "mse"):
                max_diff[field] = max(max_diff[field], abs(new[field] - old[field]))
                if not math.isclose(new[field], old[field], rel_tol=1e-10, abs_tol=1e-14 if field == "qlike" else 1e-18):
                    numeric_errors.append({"key": key(row), "field": field})
            if method in ("trailing20", "ewma094"):
                past = [math.log(prices[j] / prices[j - 1]) for j in range(t - 503, t + 1)]
                expected = math.fsum(r * r for r in (past[-20:] if method == "trailing20" else past[:20])) / 20
                if method == "ewma094":
                    for r in past[20:]:
                        expected = .94 * expected + .06 * r * r
                max_diff["trailing_or_ewma"] = max(max_diff["trailing_or_ewma"], abs(prediction - expected))
                if not all(math.isclose(v, expected, rel_tol=1e-10, abs_tol=1e-15) for v in values):
                    numeric_errors.append({"key": key(row), "field": "simple_model_reconstruction"})
            elif row["fit"]["convergence_flag"] != 0 or not row["fit"]["optimizer_success"]:
                failure_errors.append(key(row))
        elif row["state"] == "failed":
            if any(k in row or k in old for k in ("forecast_variance", "daily_variance", "qlike", "mse")):
                failure_errors.append(key(row))
        else:
            failure_errors.append(key(row))
        reconstructed[key(row)] = new
    check("input_hashes_cutoffs_and_scored_metadata", not metadata_errors, metadata_errors[:10])
    check("independent_targets_losses_and_simple_forecasts", not numeric_errors, {"max_absolute_difference": max_diff, "errors": numeric_errors[:10]})
    check("failed_fits_preserved_without_forecasts_or_losses", not failure_errors, failure_errors)
    check("report_failures_exact", report["failed_forecasts"] == [r for r in forecasts if r["state"] == "failed"])
    all_cases = {(s, d, h) for s, d, h, _ in reconstructed}
    summaries = []
    summary_errors = []
    for row in report["summary"]:
        group = row["group"]
        members = panel["symbols"] if group == "stocks" else [panel["benchmark"]] if group == "benchmark" else symbols if group == "all" else [group]
        horizon, method = row["horizon"], row["method"]
        population = sorted(k for k in all_cases if k[0] in members and k[2] == horizon)
        available = [k for k in population if reconstructed[(*k, method)]["state"] == "completed"]
        pairwise = [k for k in available if reconstructed[(*k, "trailing20")]["state"] == "completed"]
        matched = [k for k in population if all(reconstructed[(*k, m)]["state"] == "completed" for m in ("trailing20", "ewma094", "garch11"))]
        sizes = {"expected_cases": len(population), "completed_cases": len(available), "failed_cases": len(population) - len(available), "matched_cases": len(matched), "pairwise_baseline_cases": len(pairwise)}
        if any(row[k] != v for k, v in sizes.items()):
            summary_errors.append({"group": group, "method": method, "horizon": horizon, "field": "coverage"})
        independent = {"group": group, "method": method, "horizon": horizon, **sizes}
        for mode, population in (("matched", matched), ("pairwise", pairwise)):
            if not population:
                independent[mode] = None
                if row[mode] is not None:
                    summary_errors.append({"group": group, "field": mode})
                continue
            n = len(population)
            r = [reconstructed[(*k, method)] for k in population]
            b = [reconstructed[(*k, "trailing20")] for k in population]
            mse = math.fsum(v["mse"] for v in r) / n
            baseline_mse = math.fsum(v["mse"] for v in b) / n
            predictions = math.fsum(v["prediction"] for v in r)
            stats = {"mean_qlike": math.fsum(v["qlike"] for v in r) / n, "mse": mse,
                     "qlike_difference_vs_trailing20": math.fsum(v["qlike"] - w["qlike"] for v, w in zip(r, b)) / n,
                     "mse_skill_vs_trailing20": 1 - mse / baseline_mse if baseline_mse else None,
                     "calibration_actual_over_predicted": math.fsum(v["target"] for v in r) / predictions if predictions else None}
            independent[mode] = stats
            for field, value in stats.items():
                old = row[mode][field]
                if (value is None) != (old is None) or value is not None and not math.isclose(value, old, rel_tol=1e-9, abs_tol=1e-11 if field != "mse" else 1e-18):
                    summary_errors.append({"group": group, "method": method, "horizon": horizon, "field": mode + "." + field, "independent": value, "saved": old})
        summaries.append(independent)
    check("independent_aggregate_and_instrument_summaries", not summary_errors, {"summary_rows": len(summaries), "errors": summary_errors[:10]})
    # Shared date blocks keep contemporaneous stocks together. A date with one
    # failed fit has 32, not 33, matched stocks; sums/counts preserve pooled means.
    origin_dates = [dates[t] for t in origins]
    n_dates = len(origin_dates)
    rng = np.random.default_rng(59137)
    block_starts = rng.integers(0, n_dates, size=(5000, math.ceil(n_dates / 3)))
    draws = ((block_starts[:, :, None] + np.arange(3)) % n_dates).reshape(5000, -1)[:, :n_dates]
    bootstrap = []
    for horizon in (5, 20):
        matched = [(s, d, horizon) for d in origin_dates for s in panel["symbols"]
                   if all(reconstructed[(s, d, horizon, m)]["state"] == "completed" for m in ("trailing20", "ewma094", "garch11"))]
        for method in ("ewma094", "garch11"):
            sums, counts = [], []
            for d in origin_dates:
                day_cases = [k for k in matched if k[1] == d]
                counts.append(len(day_cases))
                sums.append(math.fsum(reconstructed[(*k, method)]["qlike"] - reconstructed[(*k, "trailing20")]["qlike"] for k in day_cases))
            sums, counts = np.asarray(sums), np.asarray(counts)
            boot_values = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
            interval = np.quantile(boot_values, [.025, .975]).tolist()
            bootstrap.append({"group": "stocks", "method": method, "horizon": horizon,
                              "matched_cases": len(matched), "origin_dates": n_dates,
                              "qlike_difference_vs_trailing20": float(sums.sum() / counts.sum()),
                              "percentile_interval_95": interval,
                              "interval_entirely_below_zero": interval[1] < 0,
                              "fraction_of_bootstrap_replicates_below_zero": float(np.mean(boot_values < 0)),
                              "date_counts": dict(zip(origin_dates, counts.tolist()))})
    return {"status": "passed" if not errors else "failed", "verified_at": datetime.now(timezone.utc).isoformat(),
            "checks": checks, "errors": errors, "forecast_rows": len(forecasts),
            "failed_forecast_rows": sum(r["state"] == "failed" for r in forecasts),
            "failed_fits": sorted({(r["symbol"], r["origin_date"]) for r in forecasts if r["state"] == "failed"}),
            "verifier_sha256": sha(Path(__file__)), "panel_sha256": sha(panel_path),
            "files": {name: sha(run / name) for name in ("protocol.json", "forecasts.jsonl", "forecast-receipt.json", "scores.jsonl", "report.json")},
            "stock_summaries_independently_recomputed": [r for r in summaries if r["group"] == "stocks"],
            "bootstrap_protocol": {"method": "paired circular date-block percentile bootstrap", "draws": 5000, "seed": 59137,
                                   "block_length_origins": 3, "same_draw_indices_across_methods_and_horizons": True,
                                   "resampling_unit": "all matched stocks at a forecast date together; pooled sum/count statistic",
                                   "interpretation": "Exploratory uncertainty conditional on this selected panel; not an untouched holdout or multiple-search correction. QLIKE differences are in score units, never percent improvement."},
            "bootstrap_results": bootstrap,
            "limits": ["Recomputed targets, simple forecasts, metrics and coverage; GARCH parameters were not independently refit.",
                       "Daily squared-return targets are noisy variance proxies. Success here does not establish trading profitability.",
                       "Retrospective all-adjusted prices and a selected surviving stock universe remain limitations."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = verify(args.panel, args.run)
    with args.output.open("x") as out:
        json.dump(report, out, indent=2, allow_nan=False)
        out.write("\n")
    print(json.dumps({"status": report["status"], "checks": len(report["checks"]), "errors": report["errors"],
                      "bootstrap": [{k: v for k, v in r.items() if k != "date_counts"} for r in report["bootstrap_results"]]}, indent=2))
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
