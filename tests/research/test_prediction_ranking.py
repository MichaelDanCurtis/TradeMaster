"""Causality and label-maturity checks for the frozen ranking experiment."""
from copy import deepcopy
from datetime import date, timedelta
import hashlib
import json
import sys

import numpy as np
import pytest

from scripts.research import prediction_ranking as ranking


def panel_fixture(n=900):
    rng = np.random.default_rng(818)
    close = 100 * np.exp(np.cumsum(rng.normal(.0002, .015, (n, 3)), axis=0))
    volume = rng.uniform(1e5, 1e7, (n, 3))
    start = date(2020, 10, 1)
    dates = []
    while len(dates) < n:
        if start.weekday() < 5:
            dates.append(start.isoformat())
        start += timedelta(days=1)
    return {"dates": dates, "symbols": ["A", "B", "C"], "benchmark": "SPY",
            "series": {s: {"close": close[:, i].tolist(), "open": (close[:, i] * 1.001).tolist(), "volume": volume[:, i].tolist()}
                       for i, s in enumerate(["A", "B", "C"])}}


def recording_fit(calls):
    def fit(x, y):
        calls.append((x.copy(), y.copy()))
        # Deliberately depend on all training data so leakage affects forecasts.
        weights = x.T @ y / len(x)
        class Model:
            def predict(self, features):
                return features @ weights
        return {"ridge": Model(), "hgb": Model()}
    return fit


def test_rank_ties_and_constants():
    actual = ranking._rank_columns(np.array([[1, 5], [1, 5], [3, 5.0]]))
    np.testing.assert_array_equal(actual, [[-.5, 0], [-.5, 0], [1, 0]])


def test_features_are_causal_and_do_not_include_skipped_month_in_momentum():
    panel = panel_fixture(800)
    close = np.column_stack([panel["series"][s]["close"] for s in panel["symbols"]])
    volume = np.column_stack([panel["series"][s]["volume"] for s in panel["symbols"]])
    original = ranking.make_features(close, volume)
    changed_close, changed_volume = close.copy(), volume.copy()
    changed_close[601:, 0] *= 9
    changed_volume[601:, 1] *= 17
    changed = ranking.make_features(changed_close, changed_volume)
    np.testing.assert_array_equal(original[:601], changed[:601])
    changed_close = close.copy()
    changed_close[580:601, 0] *= 7
    latest_changed = ranking.make_features(changed_close, volume)
    np.testing.assert_array_equal(original[600, :, 3:5], latest_changed[600, :, 3:5])
    assert np.isnan(original[:252]).all()
    assert np.isfinite(original[252:]).all()


def test_mature_origin_boundary_is_exact():
    assert ranking.mature_training_origins(273) == []
    assert ranking.mature_training_origins(274) == [252]
    assert ranking.mature_training_origins(294) == [252]
    assert ranking.mature_training_origins(295) == [252, 273]


def test_supervised_labels_use_only_mature_exits(monkeypatch):
    panel = panel_fixture()
    calls = []
    monkeypatch.setattr(ranking, "_fit_models", recording_fit(calls))
    result = ranking.generate_predictions(panel)
    assert result["origins"]
    opens = np.column_stack([panel["series"][s]["open"] for s in panel["symbols"]])
    for origin, (x, y) in zip(result["origins"], calls):
        train = np.array(ranking.mature_training_origins(origin["origin_index"]))
        assert len(train) >= 24
        assert (train + 22 <= origin["origin_index"]).all()
        assert train[-1] + 21 + 22 > origin["origin_index"]
        expected = opens[train + 22] / opens[train + 1] - 1
        expected -= expected.mean(axis=1, keepdims=True)
        np.testing.assert_allclose(y, expected.ravel(), rtol=0, atol=0)
        assert x.shape == (len(train) * 3, 10)
        assert origin["training_row_count"] == len(y)
    assert result["skipped_origins"]
    assert all("relative_return" not in row and "return" not in row for row in result["predictions"])


def test_future_perturbation_changes_outcomes_not_earlier_predictions(monkeypatch):
    panel = panel_fixture()
    monkeypatch.setattr(ranking, "_fit_models", recording_fit([]))
    original = ranking.generate_predictions(panel)
    first = original["origins"][0]["origin_index"]
    changed = deepcopy(panel)
    for field in ("open", "close", "volume"):
        values = changed["series"]["A"][field]
        for i in range(first + 1, len(values)):
            values[i] *= 1 + (i - first) / 100
    revised = ranking.generate_predictions(changed)
    original_predictions = [r for r in original["predictions"] if r["origin_index"] == first]
    revised_predictions = [r for r in revised["predictions"] if r["origin_index"] == first]
    assert original_predictions == revised_predictions
    assert original["outcomes"][:3] != revised["outcomes"][:3]


def test_benchmark_must_not_be_ranked_and_missing_values_rejected():
    panel = panel_fixture(300)
    panel["benchmark"] = "A"
    with pytest.raises(ValueError, match="benchmark"):
        ranking.generate_predictions(panel)
    panel["benchmark"] = "SPY"
    panel["series"]["A"]["open"][5] = float("nan")
    with pytest.raises(ValueError, match="finite positive"):
        ranking.generate_predictions(panel)


def test_cli_freezes_predictions_before_joining_outcomes(monkeypatch, tmp_path):
    panel = panel_fixture(820)
    path = tmp_path / "panel.json"
    path.write_text(json.dumps(panel))
    output = tmp_path / "new_run"
    monkeypatch.setattr(ranking, "_fit_models", recording_fit([]))
    original_score = ranking.score_origins
    calls = []
    def score_after_write(panel, origins):
        assert (output / "predictions.json").is_file()
        assert not (output / "outcomes.json").exists()
        frozen = json.loads((output / "predictions.json").read_text())
        assert "outcomes" not in frozen
        assert frozen["origins"] == origins
        calls.append(len(origins))
        return original_score(panel, origins)
    monkeypatch.setattr(ranking, "score_origins", score_after_write)
    monkeypatch.setattr(sys, "argv", ["prediction_ranking.py", "--panel", str(path), "--output", str(output)])
    ranking.main()
    assert len(calls) == 1 and calls[0] > 0
    actual = json.loads((output / "outcomes.json").read_text())
    assert actual["predictions_sha256"] == hashlib.sha256((output / "predictions.json").read_bytes()).hexdigest()


def test_actual_estimators_run_with_frozen_parameters_and_preserve_causality():
    pytest.importorskip("sklearn")
    rng = np.random.default_rng(21)
    x = rng.uniform(-1, 1, (240, 10))
    y = .03 * x[:, 0] + .02 * x[:, 1] ** 2
    models = ranking._fit_models(x, y)
    assert models["ridge"].alpha == 240
    assert models["ridge"].solver == "svd"
    assert models["hgb"].early_stopping is False
    assert models["hgb"].n_iter_ == 100
    assert np.std(models["hgb"].predict(x)) > 0
    panel = panel_fixture(820)
    result = ranking.generate_predictions(panel, include_outcomes=False)
    assert len(result["origins"]) == 1
    assert "outcomes" not in result
    assert len(result["predictions"]) == 9
    t = result["origins"][0]["origin_index"]
    changed = deepcopy(panel)
    for field in ("open", "close", "volume"):
        for i in range(t + 1, len(panel["dates"])):
            changed["series"]["A"][field][i] *= 1 + (i - t) / 10
    revised = ranking.generate_predictions(changed, include_outcomes=False)
    assert result["predictions"] == revised["predictions"]
