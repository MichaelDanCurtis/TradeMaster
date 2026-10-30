"""Frozen ranking models with decision-time membership and incomplete histories.

Forecast eligibility never depends on future price availability. Missing matured
training labels are counted explicitly; unresolved evaluation labels are retained.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
import sys

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.research.prediction_ranking import FEATURE_NAMES, _fit_models, _rank_columns

START = "2021-09-03"
END = "2026-09-04"
MODELS = ("momentum_12_1", "ridge", "hgb")


class Panel:
    def __init__(self, panel):
        self.symbols = list(panel["symbols"])
        self.dates = list(panel["dates"])
        if len(set(self.symbols)) != len(self.symbols) or len(self.symbols) < 2:
            raise ValueError("distinct stock symbols required")
        if panel.get("benchmark") in self.symbols:
            raise ValueError("benchmark must not be in ranked stock universe")
        parsed = [date.fromisoformat(d) for d in self.dates]
        if not parsed or any(a >= b for a, b in zip(parsed, parsed[1:])):
            raise ValueError("strictly increasing nonempty dates required")
        self.arrays = {}
        for field in ("open", "close", "volume"):
            columns = [np.asarray(panel["series"][s][field], dtype=float) for s in self.symbols]
            if any(c.shape != (len(self.dates),) for c in columns):
                raise ValueError(f"{field} arrays must align with dates")
            self.arrays[field] = np.column_stack(columns)
        membership = panel.get("membership")
        self.membership = np.asarray(membership if membership is not None else np.ones((len(self.dates), len(self.symbols)), dtype=bool))
        if self.membership.shape != (len(self.dates), len(self.symbols)) or not np.isin(self.membership, [False, True]).all():
            raise ValueError("membership must be a boolean [time, stocks] mask")
        self.membership = self.membership.astype(bool)
        invalid = (~np.isfinite(self.arrays["close"]) | (self.arrays["close"] <= 0)
                   | ~np.isfinite(self.arrays["volume"]) | (self.arrays["volume"] <= 0))
        self.invalid_prefix = np.vstack([np.zeros((1, len(self.symbols)), dtype=int), np.cumsum(invalid, axis=0)])
        self.cache = {}

    def features(self, t):
        if t in self.cache:
            return self.cache[t]
        complete = (self.invalid_prefix[t + 1] - self.invalid_prefix[t - 252] == 0) if t >= 252 else np.zeros(len(self.symbols), dtype=bool)
        indices = np.flatnonzero(self.membership[t] & complete)
        info = {"origin_index": t, "date": self.dates[t], "member_count": int(self.membership[t].sum()),
                "eligible_count": len(indices), "excluded_incomplete_history": int((self.membership[t] & ~complete).sum())}
        if len(indices) < 2:
            result = (indices, None, None, info)
        else:
            close = self.arrays["close"][t - 252:t + 1, indices]
            volume = self.arrays["volume"][t - 252:t + 1, indices]
            returns = close[1:] / close[:-1] - 1
            momentum = close[-22] / close[0] - 1
            raw = np.column_stack([
                close[-1] / close[-6] - 1, close[-1] / close[-22] - 1,
                close[-1] / close[-64] - 1, close[-22] / close[-127] - 1, momentum,
                returns[-21:].std(axis=0, ddof=1), returns[-63:].std(axis=0, ddof=1),
                close[-1] / close[-63:].max(axis=0) - 1,
                volume[-5:].mean(axis=0) / volume[-63:].mean(axis=0) - 1,
                np.log((close[-21:] * volume[-21:]).mean(axis=0)),
            ])
            if not np.isfinite(raw).all():
                raise ValueError(f"nonfinite derived features at {self.dates[t]}")
            result = (indices, _rank_columns(raw), momentum, info)
        self.cache[t] = result
        return result


def score_rows(panel, rows):
    """Keep every predicted stock, including unavailable evaluation endpoints."""
    data = Panel(panel)
    positions = {s: i for i, s in enumerate(data.symbols)}
    outcomes = []
    for row in rows:
        values = []
        for symbol in row["eligible_symbols"]:
            j = positions[symbol]
            entry = data.arrays["open"][row["entry_index"], j]
            exit_price = data.arrays["open"][row["exit_index"], j]
            valid = np.isfinite(entry) and np.isfinite(exit_price) and entry > 0 and exit_price > 0
            values.append(float(exit_price / entry - 1) if valid else None)
        available = [v for v in values if v is not None]
        mean = float(np.mean(available)) if available else None
        complete = len(available) == len(values)
        for symbol, value in zip(row["eligible_symbols"], values):
            outcomes.append({"origin_index": row["origin_index"], "date": row["date"], "symbol": symbol,
                             "entry_index": row["entry_index"], "exit_index": row["exit_index"],
                             "truncated": row["truncated"], "state": "resolved" if value is not None else "unresolved",
                             "return": value, "relative_return": value - mean if value is not None and complete else None,
                             "relative_return_scope": "complete_forecast_universe" if complete else "unavailable_due_to_missing_outcomes"})
    return outcomes


def generate_predictions(panel, *, include_outcomes=False):
    data = Panel(panel)
    first = next((t for t, d in enumerate(data.dates) if t >= 252 and d >= START), len(data.dates))
    final = next((t for t, d in enumerate(data.dates) if d == END), None)
    if final is None:
        raise ValueError("panel must contain final valuation session 2026-09-04")
    rows, failures, coverage, training_cache = [], [], [], {}
    for t in range(first, final - 1, 21):
        eligible, test, momentum, current = data.features(t)
        coverage.append(current)
        if test is None:
            failures.append({**current, "reason": "fewer_than_two_eligible_stocks"})
            continue
        mature = list(range(252, t - 22 + 1, 21))
        for o in mature:
            if o in training_cache:
                continue
            indices, features, _, info = data.features(o)
            record = {**info, "exit_index": o + 22, "resolved_label_count": 0,
                      "excluded_unresolved_labels": 0, "usable": False}
            if features is None:
                training_cache[o] = (None, None, record)
                continue
            endpoints = data.arrays["open"][[o + 1, o + 22]][:, indices]
            resolved = np.isfinite(endpoints).all(axis=0) & (endpoints > 0).all(axis=0)
            record["resolved_label_count"] = int(resolved.sum())
            record["excluded_unresolved_labels"] = int((~resolved).sum())
            if resolved.sum() < 2:
                training_cache[o] = (None, None, record)
                continue
            labels = endpoints[1, resolved] / endpoints[0, resolved] - 1
            labels -= labels.mean()
            record["usable"] = True
            training_cache[o] = (features[resolved], labels, record)
        usable = [o for o in mature if training_cache[o][2]["usable"]]
        if len(usable) < 24:
            failures.append({**current, "reason": "fewer_than_24_usable_mature_training_origins",
                             "mature_training_origin_count": len(mature), "usable_training_origin_count": len(usable)})
            continue
        x = np.concatenate([training_cache[o][0] for o in usable])
        y = np.concatenate([training_cache[o][1] for o in usable])
        fitted = _fit_models(x, y)
        scores = {"momentum_12_1": momentum.tolist()}
        scores.update({name: model.predict(test).tolist() for name, model in fitted.items()})
        if any(len(v) != len(eligible) or not np.isfinite(v).all() for v in scores.values()):
            raise ValueError(f"invalid predictions at {data.dates[t]}")
        rows.append({"origin_index": t, "date": data.dates[t], "entry_index": t + 1,
                     "exit_index": min(t + 22, final), "truncated": t + 22 > final,
                     "eligible_symbols": [data.symbols[j] for j in eligible], "scores": scores,
                     "training_origin_count": len(usable), "mature_training_origin_count": len(mature),
                     "training_row_count": len(x), "last_training_origin": usable[-1],
                     "last_training_exit_index": usable[-1] + 22,
                     "excluded_training_origins": len(mature) - len(usable),
                     "excluded_unresolved_training_labels": sum(training_cache[o][2]["excluded_unresolved_labels"] for o in mature)})
    result = {"metadata": {"schema": "prediction-wide-ranking-v1", "symbols": data.symbols,
                            "benchmark": panel.get("benchmark"), "feature_names": list(FEATURE_NAMES),
                            "models": list(MODELS), "requested_signal_start": START, "final_valuation_date": END,
                            "membership_mode": "provided_decision_time_mask" if panel.get("membership") is not None else "static_all_supplied_symbols",
                            "membership_source": panel.get("membership_source"),
                            "warmup_observations": 253, "training_step_sessions": 21,
                            "label_entry_offset": 1, "label_exit_offset": 22,
                            "minimum_usable_training_origins": 24, "ridge_alpha": "training_row_count",
                            "hgb": {"max_iter": 100, "learning_rate": .03, "max_depth": 2,
                                    "max_leaf_nodes": 4, "min_samples_leaf": 50, "l2_regularization": 1,
                                    "early_stopping": False, "random_state": 59137},
                            "scope": "Exploratory historical ranking. Missing mature labels are explicitly excluded; missing evaluation outcomes never alter forecast eligibility or authorize dropping held losses."},
              "rows": rows, "coverage": coverage, "failures": failures,
              "training_coverage": [training_cache[o][2] for o in sorted(training_cache)]}
    if include_outcomes:
        result["outcomes"] = score_rows(panel, rows)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    source = args.panel.read_bytes()
    panel = json.loads(source)
    result = generate_predictions(panel)
    result["metadata"]["panel_sha256"] = hashlib.sha256(source).hexdigest()
    result["metadata"]["runner_sha256"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    original = Path(__file__).with_name("prediction_ranking.py")
    result["metadata"]["frozen_primitives_sha256"] = hashlib.sha256(original.read_bytes()).hexdigest()
    payload = json.dumps(result, indent=2, allow_nan=False) + "\n"
    (args.output / "predictions.json").write_text(payload)
    outcomes = score_rows(panel, result["rows"])
    (args.output / "outcomes.json").write_text(json.dumps({"panel_sha256": result["metadata"]["panel_sha256"],
        "predictions_sha256": hashlib.sha256(payload.encode()).hexdigest(), "outcomes": outcomes}, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"origins": len(result["rows"]), "failures": len(result["failures"]),
                      "unresolved_outcomes": sum(r["state"] == "unresolved" for r in outcomes), "output": str(args.output)}))


if __name__ == "__main__":
    main()
