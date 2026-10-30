"""Frozen, past-only stock ranking hypotheses; no portfolio scoring or orders.

The market-residual reversal is a new five-session hypothesis. It does not
replicate the monthly, industry- and news-adjusted reversal research it cites.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import hashlib
import json
from pathlib import Path
import platform

import numpy as np


METHODS = ("plain_reversal", "residual_reversal", "momentum")
PROTOCOL = {
    "version": "market-residual-reversal-1",
    "origin_anchor": "2023-01-03",
    "origin_stride_sessions": 5,
    "origin_condition": "t >= 252 and t + 6 < number_of_sessions",
    "execution": "next open t+1; exit open t+6; parent owns portfolio weights and costs",
    "plain_reversal": "negative sum of five daily log returns ending at origin t",
    "residual_reversal": {
        "regression": "stock daily log return = intercept + beta * SPY daily log return",
        "fit_returns": 60,
        "fit_return_end_indices": "t-64 through t-5 inclusive",
        "score": "negative sum of residuals for return end indices t-4 through t inclusive",
        "fit": "OLS with intercept; centered covariance divided by centered market sum of squares",
        "zero_market_variance": "raise ValueError; no fallback or substituted score",
    },
    "momentum": "close[t-21] / close[t-252] - 1",
    "ordering": "higher scores preferred; array order equals panel symbols",
    "tuning": "none",
    "scope": "Ranking hypotheses, not predicted dollar prices or calibrated expected returns",
    "data_caveat": "Retrospective adjusted prices are not historical publication vintages; selected universe may have survivorship bias",
    "research_caveat": "SPY residuals do not isolate fundamental news or industry effects; this five-session test is not a replication",
    "source": "https://academicweb.nd.edu/~zda/Reversal.pdf",
}
SCORE_UNITS = {
    "plain_reversal": "negative decimal log return",
    "residual_reversal": "negative sum of decimal log-return residuals",
    "momentum": "decimal simple return",
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
        raise ValueError("Session dates must use YYYY-MM-DD")
    symbols = panel["symbols"]
    if not symbols or len(symbols) != len(set(symbols)):
        raise ValueError("Stock symbols must be nonempty and unique")
    if panel["benchmark"] != "SPY" or "SPY" in symbols:
        raise ValueError("SPY must be the separate benchmark, not a ranked stock")
    for symbol in [*symbols, "SPY"]:
        for field in ("open", "high", "low", "close", "volume", "vwap"):
            values = np.asarray(panel["series"][symbol][field], dtype=np.float64)
            if values.shape != (len(dates),) or not np.isfinite(values).all():
                raise ValueError(f"{symbol} {field}: incomplete or nonfinite panel")
            if field == "volume":
                if (values < 0).any():
                    raise ValueError(f"{symbol}: volume must be nonnegative")
            elif (values <= 0).any():
                raise ValueError(f"{symbol} {field}: prices must be positive")


def evaluation_origins(dates):
    anchor = next((i for i, day in enumerate(dates) if day >= PROTOCOL["origin_anchor"]), len(dates))
    return [t for t in range(anchor, len(dates), 5) if t >= 252 and t + 6 < len(dates)]


def scores_at(stock_closes, market_closes, origin):
    """Take stock-major closes and slice at origin before calculating features."""
    stocks = np.asarray(stock_closes, dtype=np.float64)
    market = np.asarray(market_closes, dtype=np.float64)
    if stocks.ndim != 2 or stocks.shape[0] == 0 or market.ndim != 1:
        raise ValueError("Expected stock-major close matrix and market close vector")
    if origin < 252 or stocks.shape[1] <= origin or len(market) <= origin:
        raise ValueError("Scores require 253 past closes including the origin")
    past = stocks[:, origin - 252:origin + 1]
    market_past = market[origin - 252:origin + 1]
    if (not np.isfinite(past).all() or not np.isfinite(market_past).all()
            or (past <= 0).any() or (market_past <= 0).any()):
        raise ValueError("Past closes must be finite and positive")

    # The last 66 closes yield 65 returns: 60 fit returns followed by five shocks.
    stock_returns = np.diff(np.log(past[:, -66:]), axis=1)
    market_returns = np.diff(np.log(market_past[-66:]))
    x = market_returns[:60]
    y = stock_returns[:, :60]
    centered_x = x - x.mean()
    denominator = float(centered_x @ centered_x)
    if denominator == 0.0:
        raise ValueError(f"Zero market variance in 60-return fit at origin {origin}")
    y_mean = y.mean(axis=1)
    beta = ((y - y_mean[:, None]) @ centered_x) / denominator
    intercept = y_mean - beta * x.mean()
    residual = stock_returns[:, 60:] - intercept[:, None] - beta[:, None] * market_returns[60:]
    result = {
        "plain_reversal": (-stock_returns[:, 60:].sum(axis=1)).tolist(),
        "residual_reversal": (-residual.sum(axis=1)).tolist(),
        "momentum": (past[:, -22] / past[:, 0] - 1.0).tolist(),
    }
    if any(not np.isfinite(value).all() for value in result.values()):
        raise ValueError(f"Nonfinite rank score at origin {origin}")
    return result


def generate_predictions(panel):
    validate_panel(panel)
    origins = evaluation_origins(panel["dates"])
    if not origins:
        raise ValueError("No eligible forecast origins under the frozen protocol")
    closes = np.asarray([panel["series"][s]["close"] for s in panel["symbols"]], dtype=np.float64)
    market = np.asarray(panel["series"]["SPY"]["close"], dtype=np.float64)
    rows = [{
        "origin_index": t, "origin_date": panel["dates"][t],
        "entry_index": t + 1, "exit_index": t + 6,
        "scores": scores_at(closes, market, t),
    } for t in origins]
    return {
        "protocol": PROTOCOL, "protocol_sha256": sha256(canonical_bytes(PROTOCOL)),
        "panel_sha256": sha256(canonical_bytes(panel)),
        "symbols": list(panel["symbols"]), "benchmark": panel["benchmark"],
        "score_units": SCORE_UNITS, "rows": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New output directory; never overwrite")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(f"Output already exists: {args.output}")
    raw = args.panel.read_bytes()
    predictions = generate_predictions(json.loads(raw))
    serialized = canonical_bytes(predictions)
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "predictions.json").write_bytes(serialized)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "input_file_sha256": sha256(raw), "panel_sha256": predictions["panel_sha256"],
        "protocol_sha256": predictions["protocol_sha256"],
        "predictions_sha256": sha256(serialized),
        "script_sha256": sha256(Path(__file__).read_bytes()),
        "python": platform.python_version(), "numpy": np.__version__,
        "origin_count": len(predictions["rows"]),
        "symbol_count": len(predictions["symbols"]),
        "state": "predictions_saved_without_evaluation",
    }
    (args.output / "manifest.json").write_bytes(canonical_bytes(manifest))
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
