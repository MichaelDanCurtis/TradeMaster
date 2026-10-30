from copy import deepcopy
from datetime import date, timedelta
import json
import sys

import numpy as np
import pytest

from scripts.research import prediction_reversal as reversal


def price_path(returns, initial=100.0):
    return initial * np.exp(np.r_[0.0, np.cumsum(returns)])


def panel_fixture():
    start = date(2022, 1, 3)
    dates = [(start + timedelta(days=i)).isoformat() for i in range(500)
             if (start + timedelta(days=i)).weekday() < 5]
    x = .002 * np.sin(np.arange(len(dates) - 1) / 3.0)
    closes = {"SPY": price_path(x), "AAA": price_path(.0001 + 1.5*x),
              "BBB": price_path(-.0002 + .7*x + .001*np.cos(np.arange(len(x))))}
    return {
        "dates": dates, "symbols": ["AAA", "BBB"], "benchmark": "SPY",
        "series": {symbol: {"open": p.tolist(), "close": p.tolist(),
                            "high": (p*1.01).tolist(), "low": (p*.99).tolist(),
                            "vwap": p.tolist(), "volume": [1000.0] * len(p)}
                   for symbol, p in closes.items()},
    }


def test_known_intercept_beta_and_shock_units():
    market_returns = .002 * np.sin(np.arange(252) / 2.0)
    stock_returns = .0003 + 1.75 * market_returns
    stock_returns[-5:] += .01
    stock = price_path(stock_returns)
    scores = reversal.scores_at([stock], price_path(market_returns), 252)
    assert scores["residual_reversal"] == pytest.approx([-.05], abs=1e-12)
    assert scores["plain_reversal"] == pytest.approx([-sum(stock_returns[-5:])], abs=1e-12)
    assert scores["momentum"] == pytest.approx([stock[231]/stock[0]-1], abs=1e-12)


def test_latest_five_returns_do_not_enter_beta_fit():
    x = .003 * np.cos(np.arange(252) / 3.0)
    y = .0001 + 2*x
    before = reversal.scores_at([price_path(y)], price_path(x), 252)
    y[-5:] += .02
    after = reversal.scores_at([price_path(y)], price_path(x), 252)
    assert before["residual_reversal"] == pytest.approx([0], abs=1e-12)
    assert after["residual_reversal"] == pytest.approx([-.10], abs=1e-12)


def test_fit_boundaries_match_independent_least_squares():
    rng = np.random.default_rng(53219)
    x = rng.normal(.0002, .01, 400)
    y = rng.normal(.0001, .015, (2, 400)) + 1.3*x
    stocks = np.array([price_path(r) for r in y])
    t = 321
    # Return array element k has ending close index k+1.
    fit_x = x[t-65:t-5]
    fit_y = y[:, t-65:t-5]
    coefficients = np.linalg.lstsq(np.column_stack([np.ones(60), fit_x]), fit_y.T, rcond=None)[0]
    residual = y[:, t-5:t] - coefficients[0, :, None] - coefficients[1, :, None]*x[t-5:t]
    scores = reversal.scores_at(stocks, price_path(x), t)
    assert scores["residual_reversal"] == pytest.approx((-residual.sum(axis=1)).tolist(), abs=1e-12)


def test_future_price_changes_cannot_change_saved_earlier_scores():
    panel = panel_fixture()
    before = reversal.generate_predictions(panel)
    t = before["rows"][0]["origin_index"]
    changed = deepcopy(panel)
    for series in changed["series"].values():
        for field, values in series.items():
            values[t+1:] = [v * (10 + k*.13) for k, v in enumerate(values[t+1:])]
    after = reversal.generate_predictions(changed)
    assert before["rows"][0] == after["rows"][0]
    assert before["panel_sha256"] != after["panel_sha256"]
    assert before["rows"][2]["scores"] != after["rows"][2]["scores"]


def test_prefix_only_input_and_stock_order_are_preserved():
    panel = panel_fixture()
    result = reversal.generate_predictions(panel)
    row = result["rows"][0]
    t = row["origin_index"]
    stocks = [panel["series"][s]["close"][:t+1] for s in panel["symbols"]]
    prefix_scores = reversal.scores_at(stocks, panel["series"]["SPY"]["close"][:t+1], t)
    assert row["scores"] == prefix_scores
    reversed_panel = deepcopy(panel)
    reversed_panel["symbols"].reverse()
    reversed_row = reversal.generate_predictions(reversed_panel)["rows"][0]
    for method in reversal.METHODS:
        assert reversed_row["scores"][method] == row["scores"][method][::-1]


def test_origins_keep_anchor_stride_and_five_open_to_open_sessions():
    panel = panel_fixture()
    result = reversal.generate_predictions(panel)
    dates = panel["dates"]
    anchor = next(i for i, d in enumerate(dates) if d >= "2023-01-03")
    assert result["rows"][0]["origin_index"] == anchor
    for row in result["rows"]:
        t = row["origin_index"]
        assert t >= 252 and (t-anchor) % 5 == 0 and t+6 < len(dates)
        assert row["entry_index"] == t+1 and row["exit_index"] == t+6
        assert row["exit_index"] - row["entry_index"] == 5
        assert set(row) == {"origin_index", "origin_date", "entry_index", "exit_index", "scores"}


def test_zero_market_variance_fails_without_silent_fallback():
    panel = panel_fixture()
    panel["series"]["SPY"]["close"] = [100.] * len(panel["dates"])
    with pytest.raises(ValueError, match="Zero market variance"):
        reversal.generate_predictions(panel)


@pytest.mark.parametrize("defect", ["duplicate_dates", "missing_bar", "negative_close", "nan", "benchmark"])
def test_invalid_panels_fail(defect):
    panel = panel_fixture()
    if defect == "duplicate_dates":
        panel["dates"][2] = panel["dates"][1]
    elif defect == "missing_bar":
        panel["series"]["AAA"]["close"].pop()
    elif defect == "negative_close":
        panel["series"]["AAA"]["close"][10] = -1
    elif defect == "nan":
        panel["series"]["AAA"]["close"][10] = float("nan")
    else:
        panel["symbols"].append("SPY")
    with pytest.raises(ValueError):
        reversal.generate_predictions(panel)


def test_no_eligible_origins_fails():
    panel = panel_fixture()
    panel["dates"] = panel["dates"][:252]
    for series in panel["series"].values():
        for field in series:
            series[field] = series[field][:252]
    with pytest.raises(ValueError, match="No eligible"):
        reversal.generate_predictions(panel)


def test_cli_persists_hashed_predictions_and_refuses_overwrite(tmp_path, monkeypatch):
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(json.dumps(panel_fixture()))
    output = tmp_path / "predictions"
    monkeypatch.setattr(sys, "argv", ["prediction_reversal.py", "--panel", str(panel_path), "--output", str(output)])
    reversal.main()
    manifest = json.loads((output / "manifest.json").read_bytes())
    predictions_bytes = (output / "predictions.json").read_bytes()
    predictions = json.loads(predictions_bytes)
    assert manifest["input_file_sha256"] == reversal.sha256(panel_path.read_bytes())
    assert manifest["predictions_sha256"] == reversal.sha256(predictions_bytes)
    assert manifest["panel_sha256"] == predictions["panel_sha256"]
    assert manifest["state"] == "predictions_saved_without_evaluation"
    assert set(p.name for p in output.iterdir()) == {"manifest.json", "predictions.json"}
    with pytest.raises(FileExistsError):
        reversal.main()
    assert (output / "predictions.json").read_bytes() == predictions_bytes
