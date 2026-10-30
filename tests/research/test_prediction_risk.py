"""Causality, numerical units, and evidence separation for the risk experiment."""
import copy
import json
import math
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from scripts.research import prediction_risk as risk


def fake_fit(returns):
    # Deliberately depends on the full supplied input to catch future leakage.
    variance = float(np.mean(returns ** 2))
    return {"state": "completed", "daily_variance": [variance + 1e-10 * i for i in range(20)]}


def panel_fixture():
    n = 650
    dates = np.busday_offset(np.datetime64("2021-01-01"), np.arange(n)).astype(str).tolist()
    panel = {"dates": dates, "symbols": ["AAA"], "benchmark": "SPY", "series": {}}
    for i, symbol in enumerate(("AAA", "SPY")):
        close = (100 * np.exp(np.cumsum(.008 * np.sin(np.arange(n) / (4 + i)) + .0001))).tolist()
        panel["series"][symbol] = {key: close.copy() for key in ("open", "high", "low", "close", "vwap")}
        panel["series"][symbol]["volume"] = [1000.0] * n
    return panel


def test_forecast_does_not_receive_future_prices():
    panel = panel_fixture()
    t = risk.evaluation_origins(panel["dates"])[0]
    close = panel["series"]["AAA"]["close"]
    seen = []

    def spy_fit(returns):
        seen.append(returns.copy())
        return fake_fit(returns)

    before = risk.forecast_at(close, t, spy_fit)
    changed = close.copy()
    changed[t + 1:] = [v * (4 + i) for i, v in enumerate(changed[t + 1:])]
    after = risk.forecast_at(changed, t, spy_fit)
    assert before == after
    assert len(seen[0]) == 504
    np.testing.assert_array_equal(seen[0], np.diff(np.log(close[t - 504:t + 1])))
    np.testing.assert_array_equal(seen[0], seen[1])
    changed[t] *= 1.05
    assert risk.forecast_at(changed, t, fake_fit) != before


def test_fixed_origin_calendar_and_horizon_boundary():
    panel = panel_fixture()
    dates = panel["dates"]
    anchor = next(i for i, d in enumerate(dates) if d >= "2023-01-03")
    expected = [t for t in range(anchor, len(dates), 21) if t >= 504 and t + 22 < len(dates)]
    assert risk.evaluation_origins(dates) == expected
    rows = list(risk.forecast_rows(panel, fake_fit))
    assert {r["origin_index"] for r in rows if r["symbol"] == "AAA"} == set(expected)
    assert {r["origin_index"] for r in rows if r["symbol"] == "SPY"} == set(expected)
    assert len(rows) == len(expected) * 2 * 3 * 2
    assert all(r["last_input_date"] == r["origin_date"] for r in rows)


def test_zero_mean_variance_units_and_losses():
    returns = np.full(550, .01)
    close = np.exp(np.r_[0.0, np.cumsum(returns)])
    forecasts, _ = risk.forecast_at(close, 520, fake_fit)
    assert forecasts["trailing20"]["daily_variance"][0] == pytest.approx(.0001)
    assert forecasts["ewma094"]["daily_variance"][0] == pytest.approx(.0001)
    # A variance target uses squared daily returns, not the squared H-day return.
    panel = panel_fixture()
    for series in panel["series"].values():
        series["close"] = np.exp(np.arange(len(panel["dates"])) * .01).tolist()
    scores = list(risk.score_rows(panel, risk.forecast_rows(panel, fake_fit)))
    for row in scores:
        assert row["target_variance"] == pytest.approx(.0001)
    exact = risk.variance_losses(.0001, .0001)
    assert exact["mse"] == 0
    assert exact["qlike"] == pytest.approx(math.log(.0001) + 1)
    zero = risk.variance_losses(0, 0)
    assert zero["qlike"] == pytest.approx(math.log(1e-12))
    assert zero["mse"] == 0
    with pytest.raises(ValueError):
        risk.variance_losses(1, float("nan"))


def test_garch_percent_units_optimizer_and_analytic_horizon(monkeypatch):
    recorded = {}

    class FakeModel:
        def fit(self, **kwargs):
            recorded["fit"] = kwargs
            return FakeResult()

    class FakeResult:
        convergence_flag = 0
        optimization_result = SimpleNamespace(success=True, message="ok")
        params = {"omega": .1, "alpha[1]": .05, "beta[1]": .90}

        def forecast(self, **kwargs):
            recorded["forecast"] = kwargs
            return SimpleNamespace(variance=SimpleNamespace(iloc={-1: np.arange(1, 21, dtype=float)}))

    def arch_model(returns, **kwargs):
        recorded["returns"] = returns
        recorded["model"] = kwargs
        return FakeModel()

    monkeypatch.setitem(sys.modules, "arch", SimpleNamespace(arch_model=arch_model))
    returns = np.array([.01, -.02] * 252)
    result = risk.garch_forecast(returns)
    np.testing.assert_array_equal(recorded["returns"], 100 * returns)
    assert recorded["model"] == {"mean": "Zero", "vol": "GARCH", "p": 1, "o": 0, "q": 1, "dist": "normal", "rescale": False}
    assert recorded["fit"]["options"] == {"maxiter": 1000}
    assert recorded["fit"]["tol"] == 1e-8
    assert recorded["forecast"] == {"horizon": 20, "method": "analytic", "reindex": False}
    np.testing.assert_array_equal(result["daily_variance"], np.arange(1, 21) / 10000)


def test_garch_convergence_failure_does_not_forecast(monkeypatch):
    class FakeResult:
        convergence_flag = 9
        optimization_result = SimpleNamespace(success=False, message="iteration limit")
        params = {"omega": .1}

        def forecast(self, **kwargs):
            raise AssertionError("Nonconverged fits must not be used")

    monkeypatch.setitem(sys.modules, "arch", SimpleNamespace(arch_model=lambda *a, **k:
                        SimpleNamespace(fit=lambda **kwargs: FakeResult())))
    result = risk.garch_forecast(np.full(504, .01))
    assert result["state"] == "failed"
    assert "daily_variance" not in result
    assert result["fit"]["convergence_flag"] == 9


def test_failed_model_is_not_filled_in_or_removed_from_coverage():
    panel = panel_fixture()
    calls = 0

    def fail_first(returns):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("deliberate fit failure")
        return fake_fit(returns)

    forecasts = list(risk.forecast_rows(panel, fail_first))
    failures = [r for r in forecasts if r["state"] == "failed"]
    assert len(failures) == 2
    assert all("forecast_variance" not in r and r["method"] == "garch11" for r in failures)
    summary = risk.summarize(list(risk.score_rows(panel, forecasts)), panel["symbols"], "SPY")
    garch = next(r for r in summary if r["group"] == "all" and r["horizon"] == 5 and r["method"] == "garch11")
    baseline = next(r for r in summary if r["group"] == "all" and r["horizon"] == 5 and r["method"] == "trailing20")
    assert garch["failed_cases"] == 1
    assert garch["matched_cases"] == baseline["matched_cases"] == garch["expected_cases"] - 1
    assert baseline["pairwise_baseline_cases"] == baseline["expected_cases"]
    assert baseline["matched"]["qlike_difference_vs_trailing20"] == 0


def test_predictions_are_persisted_before_targets_are_scored(tmp_path, monkeypatch):
    panel_path = tmp_path / "panel.json"
    panel_path.write_text(json.dumps(panel_fixture()))
    before = panel_path.read_bytes()
    output = tmp_path / "run"
    original_score_rows = risk.score_rows
    called = []

    def inspect_then_score(panel, forecasts):
        receipt = json.loads((output / "forecast-receipt.json").read_text())
        raw_forecasts = (output / "forecasts.jsonl").read_bytes()
        assert receipt["forecast_sha256"] == risk.sha256(raw_forecasts)
        assert all("target_variance" not in r and "qlike" not in r for r in forecasts)
        assert not (output / "scores.jsonl").exists()
        called.append(True)
        return original_score_rows(panel, forecasts)

    monkeypatch.setattr(risk, "score_rows", inspect_then_score)
    report = risk.run(panel_path, output, fake_fit)
    assert called == [True]
    assert panel_path.read_bytes() == before
    assert report["failed_forecasts"] == []
    assert len((output / "scores.jsonl").read_text().splitlines()) == report["rows"]
    with pytest.raises(FileExistsError):
        risk.run(panel_path, output, fake_fit)


def test_panel_rejects_missing_and_nonpositive_closes():
    panel = panel_fixture()
    risk.validate_panel(panel)
    malformed = copy.deepcopy(panel)
    malformed["series"]["AAA"]["close"][100] = 0
    with pytest.raises(ValueError, match="positive"):
        risk.validate_panel(malformed)
    malformed = copy.deepcopy(panel)
    malformed["series"]["AAA"]["vwap"].pop()
    with pytest.raises(ValueError, match="incomplete"):
        risk.validate_panel(malformed)
