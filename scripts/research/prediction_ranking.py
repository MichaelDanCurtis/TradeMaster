"""Frozen, chronological stock-ranking experiment. No brokerage actions.

This is an exploratory adaptation, not a replication of published portfolios.
The CLI stores forecasts and subsequently observed outcomes in separate files.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path

import numpy as np


FEATURE_NAMES = (
    "return_5", "return_21", "return_63", "momentum_126_skip_21",
    "momentum_252_skip_21", "volatility_21", "volatility_63",
    "drawdown_63", "volume_ratio_5_63", "log_dollar_volume_21",
)
MODELS = ("momentum_12_1", "ridge", "hgb")
WARMUP = 252
STEP = 21
EXIT_OFFSET = 22
MIN_TRAINING_ORIGINS = 24


def _rank_columns(values: np.ndarray) -> np.ndarray:
    """Average tied ranks, separately per feature, mapped to [-1, 1]."""
    result = np.zeros_like(values, dtype=float)
    n = len(values)
    if n < 2:
        return result
    for feature in range(values.shape[1]):
        column = values[:, feature]
        unique, inverse, counts = np.unique(column, return_inverse=True, return_counts=True)
        if len(unique) == 1:
            continue
        ends = np.cumsum(counts)
        average_ranks_zero_based = ends - (counts + 1) / 2
        result[:, feature] = 2 * average_ranks_zero_based[inverse] / (n - 1) - 1
    return result


def make_features(close, volume) -> np.ndarray:
    """Return [time, stocks, 10] within-date ranks; warmup rows are NaN.

    All windows end at the decision close. Volatility uses sample standard
    deviation of simple daily returns. Inputs must already be split-consistent.
    """
    close, volume = np.asarray(close, dtype=float), np.asarray(volume, dtype=float)
    if close.ndim != 2 or close.shape != volume.shape:
        raise ValueError("close and volume must have matching [time, stocks] shapes")
    if close.shape[1] < 2:
        raise ValueError("ranking requires at least two stocks")
    if not np.isfinite(close).all() or not np.isfinite(volume).all():
        raise ValueError("nonfinite close or volume")
    if (close <= 0).any() or (volume <= 0).any():
        raise ValueError("close and volume must be positive")
    features = np.full((*close.shape, len(FEATURE_NAMES)), np.nan)
    returns = np.empty_like(close)
    returns[0] = np.nan
    returns[1:] = close[1:] / close[:-1] - 1
    for t in range(WARMUP, len(close)):
        raw = np.column_stack([
            close[t] / close[t - 5] - 1,
            close[t] / close[t - 21] - 1,
            close[t] / close[t - 63] - 1,
            close[t - 21] / close[t - 126] - 1,
            close[t - 21] / close[t - 252] - 1,
            np.std(returns[t - 20:t + 1], axis=0, ddof=1),
            np.std(returns[t - 62:t + 1], axis=0, ddof=1),
            close[t] / np.max(close[t - 62:t + 1], axis=0) - 1,
            np.mean(volume[t - 4:t + 1], axis=0) / np.mean(volume[t - 62:t + 1], axis=0) - 1,
            np.log(np.mean(close[t - 20:t + 1] * volume[t - 20:t + 1], axis=0)),
        ])
        if not np.isfinite(raw).all():
            raise ValueError(f"nonfinite feature at index {t}")
        features[t] = _rank_columns(raw)
    return features


def mature_training_origins(t: int) -> list[int]:
    """An exit at today's open is known by today's decision close."""
    return list(range(WARMUP, t - EXIT_OFFSET + 1, STEP))


def _fit_models(x, y):
    # sklearn is loaded only when fitting, keeping feature inspection lightweight.
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.linear_model import Ridge

    ridge = Ridge(alpha=len(x), fit_intercept=True, solver="svd").fit(x, y)
    hgb = HistGradientBoostingRegressor(
        loss="squared_error", max_iter=100, learning_rate=.03,
        max_depth=2, max_leaf_nodes=4, min_samples_leaf=50,
        l2_regularization=1, early_stopping=False, random_state=59137,
    ).fit(x, y)
    return {"ridge": ridge, "hgb": hgb}


def score_origins(panel, origins) -> list[dict]:
    """Join realized returns only after forecasts have been generated/frozen."""
    symbols = list(panel["symbols"])
    dates = panel["dates"]
    opens = np.column_stack([panel["series"][s]["open"] for s in symbols]).astype(float)
    outcomes = []
    for origin in origins:
        t = origin["origin_index"]
        if (t < 0 or t + EXIT_OFFSET >= len(dates) or origin["date"] != dates[t]
                or origin["entry_index"] != t + 1 or origin["exit_index"] != t + EXIT_OFFSET):
            raise ValueError("outcome origin does not match frozen horizon")
        endpoints = opens[[t + 1, t + EXIT_OFFSET]]
        if not np.isfinite(endpoints).all() or (endpoints <= 0).any():
            raise ValueError("outcome endpoints must be finite positive opens")
        actual = endpoints[1] / endpoints[0] - 1
        relative = actual - actual.mean()
        for s, value, rel in zip(symbols, actual, relative):
            outcomes.append({"origin_index": t, "date": dates[t], "symbol": s,
                             "entry_index": t + 1, "exit_index": t + EXIT_OFFSET,
                             "return": float(value), "relative_return": float(rel)})
    return outcomes


def generate_predictions(panel, *, include_outcomes=True) -> dict:
    """Generate long-form predictions and separate outcomes on frozen origins.

    `panel` contains dates, symbols (stocks only), benchmark (e.g. SPY), and
    series[symbol][open/close/volume] arrays. Other OHLCV fields are preserved
    by the caller but not required by these models. No result-based search.
    """
    dates = list(panel["dates"])
    symbols = list(panel["symbols"])
    if len(set(symbols)) != len(symbols) or len(symbols) < 2:
        raise ValueError("symbols must contain distinct stocks")
    if panel.get("benchmark") in symbols:
        raise ValueError("benchmark must be excluded from stock-ranking universe")
    parsed_dates = [date.fromisoformat(d) for d in dates]
    if any(a >= b for a, b in zip(parsed_dates, parsed_dates[1:])):
        raise ValueError("dates must be strictly increasing")
    arrays = {}
    for field in ("open", "close", "volume"):
        columns = [np.asarray(panel["series"][s][field], dtype=float) for s in symbols]
        if any(c.shape != (len(dates),) for c in columns):
            raise ValueError(f"{field} must align with every date")
        arrays[field] = np.column_stack(columns)
        if not np.isfinite(arrays[field]).all() or (arrays[field] <= 0).any():
            raise ValueError(f"{field} must contain finite positive values")
    features = make_features(arrays["close"], arrays["volume"])
    first = next((t for t, d in enumerate(parsed_dates) if t >= WARMUP and d >= date(2023, 1, 3)), len(dates))
    predictions, origins, skipped = [], [], []
    for t in range(first, len(dates) - EXIT_OFFSET, STEP):
        training_origins = mature_training_origins(t)
        if len(training_origins) < MIN_TRAINING_ORIGINS:
            skipped.append({"origin_index": t, "date": dates[t], "reason": "fewer_than_24_mature_training_origins", "training_origin_count": len(training_origins)})
            continue
        train = np.asarray(training_origins)
        training_returns = arrays["open"][train + EXIT_OFFSET] / arrays["open"][train + 1] - 1
        training_labels = training_returns - training_returns.mean(axis=1, keepdims=True)
        x = features[train].reshape(-1, len(FEATURE_NAMES))
        fitted = _fit_models(x, training_labels.ravel())
        scores = {"momentum_12_1": arrays["close"][t - 21] / arrays["close"][t - WARMUP] - 1}
        scores.update({name: model.predict(features[t]) for name, model in fitted.items()})
        origin = {
            "origin_index": t, "date": dates[t], "entry_index": t + 1,
            "exit_index": t + EXIT_OFFSET,
            "training_origin_count": len(training_origins), "training_row_count": len(x),
            "last_training_origin": training_origins[-1],
            "last_training_exit_index": training_origins[-1] + EXIT_OFFSET,
        }
        origins.append(origin)
        for model in MODELS:
            if np.asarray(scores[model]).shape != (len(symbols),) or not np.isfinite(scores[model]).all():
                raise ValueError(f"invalid predictions for {model} at {dates[t]}")
            for s, score in zip(symbols, scores[model]):
                predictions.append({**origin, "symbol": s, "model": model, "score": float(score)})
    result = {
        "metadata": {
            "schema": "prediction-ranking-v1", "symbols": symbols,
            "benchmark": panel.get("benchmark"), "feature_names": list(FEATURE_NAMES),
            "models": list(MODELS), "warmup_sessions": WARMUP, "step_sessions": STEP,
            "entry_offset": 1, "exit_offset": EXIT_OFFSET,
            "minimum_training_origins": MIN_TRAINING_ORIGINS,
            "ridge_mean_squared_error_penalty": 1.0,
            "hgb": {"max_iter": 100, "learning_rate": .03, "max_depth": 2,
                    "max_leaf_nodes": 4, "min_samples_leaf": 50,
                    "l2_regularization": 1, "early_stopping": False, "random_state": 59137},
            "first_available_date": dates[0] if dates else None,
            "last_available_date": dates[-1] if dates else None,
            "scope": "Exploratory historical ranking; no parameter search, orders, or profitability qualification.",
        },
        "origins": origins, "predictions": predictions,
        "skipped_origins": skipped,
    }
    if include_outcomes:
        result["outcomes"] = score_origins(panel, origins)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.panel.read_bytes()
    panel = json.loads(source)
    result = generate_predictions(panel, include_outcomes=False)
    metadata = result["metadata"]
    metadata["panel_sha256"] = hashlib.sha256(source).hexdigest()
    metadata["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    encoded = json.dumps(result, indent=2, allow_nan=False) + "\n"
    (args.output / "predictions.json").write_text(encoded)
    outcomes = score_origins(panel, result["origins"])
    (args.output / "outcomes.json").write_text(json.dumps({
        "panel_sha256": metadata["panel_sha256"],
        "predictions_sha256": hashlib.sha256(encoded.encode()).hexdigest(),
        "outcomes": outcomes,
    }, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"origins": len(result["origins"]), "predictions": len(result["predictions"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
