from copy import deepcopy

import numpy as np
import pytest

from scripts.research.insider_quality_final import quality_at, controlled_weights, trailing_returns


def facts(income=10, ocf=20, capex=5):
    return {metric: [{"value": value, "start": None if metric == "assets" else "2019-01-01",
                      "end": "2019-12-31", "filed": "2020-02-01", "accession": "0000000001-20-000001",
                      "priority": 0, "tag": metric}]
            for metric, value in [("income", income), ("ocf", ocf), ("capex", capex), ("assets", 100)]}


def test_quality_excludes_same_day_and_future_filing():
    rows = facts()
    assert quality_at(rows, "2020-02-01")["state"] == "unknown"
    assert quality_at(rows, "2020-02-02")["state"] == "pass"
    future = deepcopy(rows)
    for metric in future:
        future[metric].append({**future[metric][0], "filed": "2022-02-01", "value": -100,
                               "accession": "0000000001-22-000002"})
    assert quality_at(future, "2020-02-02") == quality_at(rows, "2020-02-02")


@pytest.mark.parametrize("metric,value", [("income", 0), ("income", -1), ("ocf", 0), ("ocf", -1), ("capex", 20), ("capex", 21)])
def test_known_unprofitable_or_cash_consuming_firms_fail(metric, value):
    rows = facts()
    rows[metric][0]["value"] = value
    assert quality_at(rows, "2020-02-02")["state"] == "fail"


def test_different_filing_vintages_cannot_be_combined():
    rows = facts()
    rows["assets"][0]["accession"] = "0000000001-20-000002"
    assert quality_at(rows, "2020-02-02")["state"] == "unknown"
    rows = facts()
    rows["capex"][0]["start"] = "2019-04-01"
    assert quality_at(rows, "2020-02-02")["state"] == "unknown"


def test_conflicting_facts_and_stale_vintages_stay_unknown():
    rows = facts()
    rows["income"].append({**rows["income"][0], "value": -3})
    assert quality_at(rows, "2020-02-02")["reason"] == "conflicting_vintage"
    assert quality_at(facts(), "2022-02-02")["state"] == "unknown"


def test_newer_negative_vintage_replaces_earlier_positive():
    rows = facts()
    for metric in rows:
        rows[metric].append({**rows[metric][0], "filed": "2020-03-01",
                             "accession": "0000000001-20-000002",
                             "value": -2 if metric == "income" else rows[metric][0]["value"]})
    assert quality_at(rows, "2020-03-02")["state"] == "fail"


@pytest.mark.parametrize("values", [[1.] * 63, [1.] * 63 + [None], [1.] * 63 + [0], [1.] * 63 + [float("inf")]])
def test_risk_history_missingness_is_not_zero_filled(values):
    assert trailing_returns(values) is None


def test_risk_history_uses_only_last_64_supplied_closes():
    history = [float("nan")] * 20 + list(np.exp(np.arange(64) * .01))
    result = trailing_returns(history)
    assert len(result) == 63
    np.testing.assert_allclose(result, np.exp(.01) - 1)


def test_position_and_sector_caps_leave_unused_cash():
    names = [f"S{i}" for i in range(12)]
    returns = {s: np.zeros(63) for s in names}
    sectors = {s: "same" for s in names}
    weights, risk = controlled_weights(names, sectors, returns)
    assert list(weights) == names[:4]
    assert max(weights.values()) == .05
    assert sum(weights.values()) == .2
    assert risk["cash_weight"] == .8


def test_correlated_risk_is_scaled_to_target_without_leverage():
    names = [f"S{i}" for i in range(20)]
    series = np.sin(np.arange(63)) * .05
    returns = {s: series for s in names}
    weights, risk = controlled_weights(names, {s: str(i // 4) for i, s in enumerate(names)}, returns)
    assert len(weights) == 20
    assert sum(weights.values()) < 1
    assert max(weights.values()) <= .05
    assert risk["estimated_volatility"] == pytest.approx(.12)
    assert all(w <= .2 + 1e-12 for w in risk["sector_weights"].values())


def test_missing_covariance_input_does_not_receive_weight():
    weights, risk = controlled_weights(["BAD", "GOOD"], {}, {"BAD": None, "GOOD": np.zeros(63)})
    assert weights == {"GOOD": .05}
    assert risk["cash_weight"] == .95


def test_spy_risk_control_has_fund_exception_to_individual_stock_cap():
    weights, risk = controlled_weights(["SPY"], {}, {"SPY": np.zeros(63)}, benchmark=True)
    assert weights == {"SPY": 1.}
    assert risk["scale"] == 1
