from copy import deepcopy
from datetime import date, timedelta
import json
import sys

import numpy as np
import pytest

from scripts.research import prediction_wide_ranking as wide
from scripts.research.prediction_ranking import make_features


def panel_fixture(n=820):
    dates = []
    current = date(2026, 9, 4)
    while len(dates) < n:
        if current.weekday() < 5:
            dates.append(current.isoformat())
        current -= timedelta(days=1)
    dates.reverse()
    rng = np.random.default_rng(905)
    close = 100 * np.exp(np.cumsum(rng.normal(0, .02, (n, 4)), axis=0))
    volume = rng.uniform(1e5, 1e7, (n, 4))
    return {"dates": dates, "symbols": list("ABCD"), "benchmark": "SPY",
            "series": {s: {"open": (close[:, j] * 1.002).tolist(), "close": close[:, j].tolist(), "volume": volume[:, j].tolist()}
                       for j, s in enumerate("ABCD")}}


def fake_fit(calls):
    def fit(x, y):
        calls.append((x.copy(), y.copy()))
        coefficients = x.T @ y / len(x)
        class Model:
            def predict(self, x):
                return x @ coefficients
        return {"ridge": Model(), "hgb": Model()}
    return fit


def test_complete_history_features_match_original_frozen_features():
    panel = panel_fixture()
    close = np.column_stack([panel["series"][s]["close"] for s in panel["symbols"]])
    volume = np.column_stack([panel["series"][s]["volume"] for s in panel["symbols"]])
    reference = make_features(close, volume)
    data = wide.Panel(panel)
    for t in (252, 477, 819):
        indices, features, _, _ = data.features(t)
        np.testing.assert_array_equal(indices, np.arange(4))
        np.testing.assert_array_equal(features, reference[t])


def test_decision_membership_and_history_only_determine_eligibility():
    panel = panel_fixture()
    panel["membership"] = np.ones((820, 4), dtype=bool).tolist()
    panel["membership"][600][1] = False
    panel["series"]["C"]["close"][500] = None
    panel["series"]["D"]["open"][601] = None
    data = wide.Panel(panel)
    indices, _, _, info = data.features(600)
    np.testing.assert_array_equal(indices, [0, 3])
    assert info["member_count"] == 3
    assert info["excluded_incomplete_history"] == 1
    assert data.features(754)[0].tolist() == [0, 1, 2, 3]


def test_mature_missing_training_labels_are_counted_and_excluded(monkeypatch):
    panel = panel_fixture()
    panel["series"]["A"]["open"][274] = None
    calls = []
    monkeypatch.setattr(wide, "_fit_models", fake_fit(calls))
    result = wide.generate_predictions(panel)
    first_training = result["training_coverage"][0]
    assert first_training["origin_index"] == 252
    assert first_training["exit_index"] == 274
    assert first_training["excluded_unresolved_labels"] == 1
    assert first_training["resolved_label_count"] == 3
    for row, (x, y) in zip(result["rows"], calls):
        assert row["last_training_exit_index"] <= row["origin_index"]
        # The same missing open ends origin252 and starts origin273.
        assert row["training_row_count"] == row["training_origin_count"] * 4 - 2
        assert row["excluded_unresolved_training_labels"] == 2
        expected = np.array([panel["series"][s]["open"][274] / panel["series"][s]["open"][253] - 1 for s in "BCD"])
        expected -= expected.mean()
        np.testing.assert_array_equal(y[:3], expected)


def test_future_missing_outcomes_do_not_remove_prediction_or_affect_past(monkeypatch):
    panel = panel_fixture()
    monkeypatch.setattr(wide, "_fit_models", fake_fit([]))
    original = wide.generate_predictions(panel)
    t = original["rows"][0]["origin_index"]
    changed = deepcopy(panel)
    changed["membership"] = np.ones((820, 4), dtype=bool).tolist()
    for i in range(t + 1, 820):
        changed["membership"][i][0] = False
        changed["series"]["A"]["open"][i] = None
        changed["series"]["A"]["close"][i] = None
        changed["series"]["A"]["volume"][i] = None
    revised = wide.generate_predictions(changed, include_outcomes=True)
    assert original["rows"][0] == revised["rows"][0]
    actual = [r for r in revised["outcomes"] if r["origin_index"] == t]
    assert len(actual) == 4
    assert actual[0]["symbol"] == "A" and actual[0]["state"] == "unresolved"
    assert actual[0]["return"] is None
    assert all(r["relative_return"] is None for r in actual)


def test_final_hold_is_truncated_without_changing_training_horizon(monkeypatch):
    monkeypatch.setattr(wide, "_fit_models", fake_fit([]))
    result = wide.generate_predictions(panel_fixture())
    assert result["rows"][-1]["truncated"] is True
    assert result["rows"][-1]["exit_index"] == 819
    assert result["rows"][-1]["entry_index"] < 819
    assert all(r["exit_index"] == r["origin_index"] + 22 for r in result["training_coverage"])


def test_cli_persists_forecasts_before_outcomes(monkeypatch, tmp_path):
    panel = panel_fixture()
    source = tmp_path / "panel.json"
    source.write_text(json.dumps(panel))
    output = tmp_path / "run"
    monkeypatch.setattr(wide, "_fit_models", fake_fit([]))
    scorer = wide.score_rows
    calls = []
    def inspect(panel, rows):
        frozen = json.loads((output / "predictions.json").read_text())
        assert frozen["rows"] == rows and "outcomes" not in frozen
        assert not (output / "outcomes.json").exists()
        calls.append(True)
        return scorer(panel, rows)
    monkeypatch.setattr(wide, "score_rows", inspect)
    monkeypatch.setattr(sys, "argv", ["wide", "--panel", str(source), "--output", str(output)])
    wide.main()
    assert calls == [True]


def test_real_estimators_support_changing_membership_and_missing_labels():
    pytest.importorskip("sklearn")
    panel = panel_fixture()
    panel["membership"] = np.ones((820, 4), dtype=bool).tolist()
    for i in range(798, 820):
        panel["membership"][i][1] = False
    panel["series"]["A"]["open"][274] = None
    result = wide.generate_predictions(panel)
    assert len(result["rows"]) == 2
    assert result["rows"][0]["eligible_symbols"] == list("ABCD")
    assert result["rows"][1]["eligible_symbols"] == list("ACD")
    for row in result["rows"]:
        assert set(row["scores"]) == {"ridge", "hgb", "momentum_12_1"}
        assert all(len(scores) == len(row["eligible_symbols"]) and np.isfinite(scores).all()
                   for scores in row["scores"].values())
        assert row["excluded_unresolved_training_labels"] == 2


def test_explicit_null_membership_is_same_static_universe_as_absent(monkeypatch):
    monkeypatch.setattr(wide, "_fit_models", fake_fit([]))
    panel = panel_fixture()
    absent = wide.generate_predictions(panel)
    panel["membership"] = None
    explicit_null = wide.generate_predictions(panel)
    assert absent == explicit_null
    assert explicit_null["metadata"]["membership_mode"] == "static_all_supplied_symbols"
