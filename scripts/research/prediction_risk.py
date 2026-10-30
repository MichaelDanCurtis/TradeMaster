"""Frozen daily-return risk comparison; never submits orders or changes its input.

The target is a mean of daily squared log returns, not intraday realized variance.
Forecasts are persisted and hashed before any evaluation targets are computed.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import platform
import warnings

import numpy as np

METHODS = ("trailing20", "ewma094", "garch11")
HORIZONS = (5, 20)
LOOKBACK = 504
VARIANCE_FLOOR = 1e-12
PROTOCOL = {
    "version": "daily-risk-1",
    "origin_anchor": "2023-01-03",
    "origin_stride_sessions": 21,
    "origin_condition": "t >= 504 and t + 22 < number_of_sessions",
    "horizons": list(HORIZONS),
    "target": "mean of next H daily squared close-to-close log returns",
    "target_caveat": "Daily squared-return proxy, not intraday realized variance; zero conditional mean assumed.",
    "data_caveat": "Retrospectively fully adjusted Alpaca prices; not historical publication vintages or a survivorship-free universe.",
    "lookback_returns": LOOKBACK,
    "trailing20": "Mean squared last 20 returns; zero mean; constant future daily variance",
    "ewma094": "Seed with mean squared first 20 of 504 returns; update remaining 484 using .94*v + .06*r*r; constant future daily variance",
    "garch11": {"mean": "Zero", "p": 1, "o": 0, "q": 1, "distribution": "normal", "rescale": False,
                  "return_multiplier": 100, "forecast_variance_divisor": 10000,
                  "fit_at_each_origin": True, "maxiter": 1000, "tol": 1e-8,
                  "forecast_method": "analytic", "failure_policy": "Preserve failure; no fallback"},
    "primary_loss": "log(max(h,1e-12)) + y/max(h,1e-12); lower is better; may be negative",
    "secondary_loss": "(y-h)^2 on daily variance scale",
    "calibration": "sum(y)/sum(h); ideal 1",
    "aggregation": "Pooled matched cases and per-instrument; stock universe separate from SPY; paired date blocks retained in raw scores",
    "scope": "Risk forecast comparison only; no profit claim, parameter search, or economic overlay",
    "sources": [
        "https://www.msci.com/documents/10199/5915b101-4206-4ba0-aee2-3449d5c7e95a",
        "https://arch.readthedocs.io/en/stable/univariate/univariate_volatility_forecasting.html",
        "https://public.econ.duke.edu/~ap172/Patton_vol_proxies_JoE_2011.pdf",
    ],
}


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha256(value: bytes):
    return hashlib.sha256(value).hexdigest()


def validate_panel(panel):
    dates = panel["dates"]
    if not dates or dates != sorted(set(dates)):
        raise ValueError("Session dates must be nonempty, unique and increasing")
    if any(date.fromisoformat(d).isoformat() != d for d in dates):
        raise ValueError("Dates must use YYYY-MM-DD")
    symbols = panel["symbols"]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("Stock symbols must be nonempty and unique")
    benchmark = panel["benchmark"]
    if benchmark in symbols:
        raise ValueError("Benchmark must be separate from stock universe")
    for symbol in [*symbols, benchmark]:
        series = panel["series"][symbol]
        for field in ("open", "high", "low", "close", "volume", "vwap"):
            values = np.asarray(series[field], dtype=np.float64)
            if values.shape != (len(dates),) or not np.isfinite(values).all():
                raise ValueError(f"{symbol} {field}: incomplete or nonfinite panel")
            if field == "close" and (values <= 0).any():
                raise ValueError(f"{symbol}: close must be positive")
            if field == "volume" and (values < 0).any():
                raise ValueError(f"{symbol}: volume must be nonnegative")


def evaluation_origins(dates):
    anchor = next((i for i, d in enumerate(dates) if d >= PROTOCOL["origin_anchor"]), len(dates))
    return [t for t in range(anchor, len(dates), 21) if t >= LOOKBACK and t + 22 < len(dates)]


def garch_forecast(returns):
    """Fit only the supplied past window; results are decimal daily variances."""
    from arch import arch_model

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = arch_model(100.0 * returns, mean="Zero", vol="GARCH", p=1, o=0,
                           q=1, dist="normal", rescale=False)
        fit = model.fit(update_freq=0, disp="off", show_warning=True, tol=1e-8,
                        options={"maxiter": 1000})
        metadata = {
            "convergence_flag": int(fit.convergence_flag),
            "optimizer_success": bool(fit.optimization_result.success),
            "optimizer_message": str(fit.optimization_result.message),
            "parameters_percent_return_units": {str(k): float(v) if math.isfinite(float(v)) else None
                                                 for k, v in fit.params.items()},
        }
        if fit.convergence_flag or not fit.optimization_result.success:
            values = None
        else:
            values = np.asarray(fit.forecast(horizon=20, method="analytic", reindex=False)
                                .variance.iloc[-1], dtype=np.float64) / 10000.0
        metadata["warnings"] = [str(item.message) for item in caught]
    if values is None:
        return {"state": "failed", "error": "GARCH optimizer did not converge", "fit": metadata}
    if values.shape != (20,) or not np.isfinite(values).all() or (values <= 0).any():
        return {"state": "failed", "error": "GARCH produced invalid forecast variance", "fit": metadata}
    return {"state": "completed", "daily_variance": values.tolist(), "fit": metadata}


def forecast_at(close, origin, fit_garch=garch_forecast):
    # Slice prices first. Neither the estimator nor its hash receives future data.
    past = np.asarray(close[origin - LOOKBACK:origin + 1], dtype=np.float64)
    if past.shape != (LOOKBACK + 1,) or (past <= 0).any() or not np.isfinite(past).all():
        raise ValueError("Forecast requires exactly 505 finite positive past closes")
    returns = np.diff(np.log(past))
    trailing = float(np.mean(returns[-20:] ** 2))
    ewma = float(np.mean(returns[:20] ** 2))
    for r in returns[20:]:
        ewma = 0.94 * ewma + 0.06 * float(r * r)
    try:
        garch = fit_garch(returns.copy())
        if garch["state"] == "completed":
            values = np.asarray(garch["daily_variance"], dtype=np.float64)
            if values.shape != (20,) or not np.isfinite(values).all() or (values <= 0).any():
                raise ValueError("Invalid fitted GARCH forecast")
    except Exception as exc:
        garch = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
    result = {
        "trailing20": {"state": "completed", "daily_variance": [trailing] * 20},
        "ewma094": {"state": "completed", "daily_variance": [ewma] * 20},
        "garch11": garch,
    }
    return result, sha256(canonical_bytes(past.tolist()))


def forecast_rows(panel, fit_garch=garch_forecast):
    dates = panel["dates"]
    for t in evaluation_origins(dates):
        for symbol in [*panel["symbols"], panel["benchmark"]]:
            forecasts, input_hash = forecast_at(panel["series"][symbol]["close"], t, fit_garch)
            for method in METHODS:
                forecast = forecasts[method]
                for horizon in HORIZONS:
                    row = {
                        "symbol": symbol, "origin_index": t, "origin_date": dates[t],
                        "last_input_date": dates[t], "first_input_close_date": dates[t - LOOKBACK],
                        "input_close_sha256": input_hash, "input_return_count": LOOKBACK,
                        "horizon": horizon, "method": method, "state": forecast["state"],
                    }
                    if "fit" in forecast:
                        row["fit"] = forecast["fit"]
                    if forecast["state"] == "completed":
                        row["daily_variance"] = forecast["daily_variance"][:horizon]
                        row["forecast_variance"] = float(np.mean(row["daily_variance"]))
                    else:
                        row["error"] = forecast.get("error", "Unknown forecast failure")
                    yield row


def variance_losses(target, forecast):
    if not math.isfinite(target) or target < 0 or not math.isfinite(forecast) or forecast < 0:
        raise ValueError("Variance scores require finite nonnegative numbers")
    safe_forecast = max(forecast, VARIANCE_FLOOR)
    return {"qlike": math.log(safe_forecast) + target / safe_forecast,
            "mse": (target - forecast) ** 2}


def score_rows(panel, forecasts):
    for forecast in forecasts:
        row = dict(forecast)
        t, horizon = row["origin_index"], row["horizon"]
        future = np.asarray(panel["series"][row["symbol"]]["close"][t:t + horizon + 1], dtype=np.float64)
        if len(future) != horizon + 1:
            raise ValueError("Incomplete evaluation outcome")
        target = float(np.mean(np.diff(np.log(future)) ** 2))
        row.update(target_variance=target, target_first_date=panel["dates"][t + 1],
                   target_last_date=panel["dates"][t + horizon])
        if row["state"] == "completed":
            row.update(variance_losses(target, row["forecast_variance"]))
        yield row


def summarize(scores, symbols, benchmark):
    """All-model matched cases for ranking; pairwise coverage also remains explicit."""
    by_case = {}
    for row in scores:
        key = (row["symbol"], row["origin_date"], row["horizon"])
        if row["method"] in by_case.setdefault(key, {}):
            raise ValueError("Duplicate forecast case")
        by_case[key][row["method"]] = row
    reports = []
    groups = [("stocks", symbols), ("benchmark", [benchmark]), ("all", [*symbols, benchmark])]
    groups.extend((symbol, [symbol]) for symbol in [*symbols, benchmark])
    for group, members in groups:
        for horizon in HORIZONS:
            cases = [c for key, c in by_case.items() if key[0] in members and key[2] == horizon]
            if not cases:
                continue
            matched = [c for c in cases if all(m in c and c[m]["state"] == "completed" for m in METHODS)]
            for method in METHODS:
                available = [c for c in cases if method in c and c[method]["state"] == "completed"]
                pairwise = [c for c in available if c.get("trailing20", {}).get("state") == "completed"]
                item = {"group": group, "horizon": horizon, "method": method,
                        "expected_cases": len(cases), "completed_cases": len(available),
                        "failed_cases": len(cases) - len(available), "matched_cases": len(matched),
                        "pairwise_baseline_cases": len(pairwise)}
                for name, population in (("matched", matched), ("pairwise", pairwise)):
                    if not population:
                        item[name] = None
                        continue
                    rows = [c[method] for c in population]
                    base = [c["trailing20"] for c in population]
                    mse = float(np.mean([r["mse"] for r in rows]))
                    base_mse = float(np.mean([r["mse"] for r in base]))
                    forecast_sum = sum(r["forecast_variance"] for r in rows)
                    item[name] = {
                        "mean_qlike": float(np.mean([r["qlike"] for r in rows])), "mse": mse,
                        "qlike_difference_vs_trailing20": float(np.mean([r["qlike"] - b["qlike"] for r, b in zip(rows, base)])),
                        "mse_skill_vs_trailing20": 1 - mse / base_mse if base_mse else None,
                        "calibration_actual_over_predicted": sum(r["target_variance"] for r in rows) / forecast_sum if forecast_sum else None,
                    }
                reports.append(item)
    return reports


def write_json(path, value):
    with path.open("xb") as out:
        out.write(json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n")


def run(panel_path, output, fit_garch=garch_forecast):
    raw = panel_path.read_bytes()
    panel = json.loads(raw)
    validate_panel(panel)
    origins = evaluation_origins(panel["dates"])
    if not origins:
        raise ValueError("No eligible evaluation origins")
    output.mkdir(parents=True, exist_ok=False)
    packages = {}
    for package in ("numpy", "scipy", "arch"):
        try:
            packages[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            packages[package] = None
    manifest = {"protocol": PROTOCOL, "protocol_sha256": sha256(canonical_bytes(PROTOCOL)),
                "panel_sha256": sha256(raw), "panel_path": str(panel_path.resolve()),
                "runner_sha256": sha256(Path(__file__).read_bytes()),
                "started_at": datetime.now(timezone.utc).isoformat(),
                "python": platform.python_version(), "packages": packages,
                "symbols": panel["symbols"], "benchmark": panel["benchmark"],
                "origin_dates": [panel["dates"][t] for t in origins]}
    write_json(output / "protocol.json", manifest)
    forecast_path = output / "forecasts.jsonl"
    count = 0
    with forecast_path.open("xb") as out:
        for row in forecast_rows(panel, fit_garch):
            out.write(canonical_bytes(row) + b"\n")
            count += 1
            if count % (len(METHODS) * len(HORIZONS) * (len(panel["symbols"]) + 1)) == 0:
                out.flush()
                print(json.dumps({"stage": "forecasting", "origin": row["origin_date"], "rows_saved": count}), flush=True)
    # The forecast receipt exists before score_rows is invoked, and hashes the
    # exact bytes subsequently re-read for scoring. Outcomes cannot alter it.
    frozen_forecast_bytes = forecast_path.read_bytes()
    receipt = {"forecast_sha256": sha256(frozen_forecast_bytes), "rows": count,
               "forecasts_frozen_at": datetime.now(timezone.utc).isoformat()}
    write_json(output / "forecast-receipt.json", receipt)
    if sha256(panel_path.read_bytes()) != manifest["panel_sha256"]:
        raise ValueError("Input panel changed during forecasting")
    frozen_rows = [json.loads(line) for line in frozen_forecast_bytes.splitlines()]
    scores = list(score_rows(panel, frozen_rows))
    with (output / "scores.jsonl").open("xb") as out:
        for row in scores:
            out.write(canonical_bytes(row) + b"\n")
    report = {"protocol_sha256": manifest["protocol_sha256"], "panel_sha256": manifest["panel_sha256"],
              **receipt, "scored_at": datetime.now(timezone.utc).isoformat(),
              "summary": summarize(scores, panel["symbols"], panel["benchmark"]),
              "failed_forecasts": [r for r in frozen_rows if r["state"] != "completed"],
              "caveats": [PROTOCOL["target_caveat"], PROTOCOL["data_caveat"], PROTOCOL["scope"],
                          "Monthly origins reduce overlapping targets; instruments and nearby dates remain dependent. No independence-based significance claim."]}
    write_json(output / "report.json", report)
    lines = ["# Historical risk forecast comparison", "", *[f"- {c}" for c in report["caveats"]], "",
             "All-model matched cases below. Lower QLIKE difference and higher MSE skill are better.", "",
             "| Group | Horizon | Method | Complete / expected | Matched | QLIKE difference vs trailing20 | MSE skill | Calibration |",
             "|---|---:|---|---:|---:|---:|---:|---:|"]
    for row in report["summary"]:
        stats = row["matched"]
        fmt = lambda v: "unavailable" if v is None else f"{v:.6g}"
        metrics = [fmt(stats[k]) if stats else "unavailable" for k in
                   ("qlike_difference_vs_trailing20", "mse_skill_vs_trailing20", "calibration_actual_over_predicted")]
        lines.append(f"| {row['group']} | {row['horizon']} | {row['method']} | {row['completed_cases']} / {row['expected_cases']} | {row['matched_cases']} | {' | '.join(metrics)} |")
    lines.extend(["", "Pairwise baseline comparisons, full daily variance vectors, failures and hashes are in the JSON artifacts.", "",
                  f"Forecast file SHA-256: `{receipt['forecast_sha256']}`", ""])
    with (output / "report.md").open("x") as out:
        out.write("\n".join(lines))
    print(json.dumps({"stage": "completed", "output": str(output.resolve()), "forecast_rows": count,
                      "failed_rows": len(report["failed_forecasts"])}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path, help="New artifact directory; refuses overwrite")
    args = parser.parse_args()
    run(args.panel, args.output)


if __name__ == "__main__":
    main()
