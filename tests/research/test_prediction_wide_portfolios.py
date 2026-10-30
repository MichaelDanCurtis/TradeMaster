"""Missing-data, allocation and endpoint behavior of the five-year engine."""
import copy
import math

import numpy as np
import pytest

from scripts.research import prediction_wide_portfolios as portfolios
from scripts.research.prediction_wide_ranking import Panel


def panel_fixture(n=8, names=("AAA", "BBB", "CCC", "DDD")):
    panel = {"dates": np.busday_offset(np.datetime64("2021-09-03"), np.arange(n)).astype(str).tolist(),
             "symbols": list(names), "benchmark": "SPY", "series": {},
             "sectors": {s: "technology" if i < 2 else "financials" for i, s in enumerate(names)},
             "issuers": {s: "issuer_ab" if i < 2 else s for i, s in enumerate(names)},
             "universe_scope": "test", "membership": None}
    for symbol in [*names, "SPY"]:
        panel["series"][symbol] = {f: [100.] * n for f in ("open", "close", "high", "low", "vwap")}
        panel["series"][symbol]["volume"] = [1000.] * n
    return panel


def row(panel, origin=0, exit_index=7, eligible=None, scores=None):
    eligible = list(panel["symbols"] if eligible is None else eligible)
    scores = scores if scores is not None else list(range(len(eligible), 0, -1))
    return {"origin_index": origin, "date": panel["dates"][origin], "entry_index": origin + 1,
            "exit_index": exit_index, "truncated": exit_index < origin + 22,
            "eligible_symbols": eligible, "scores": {m: scores.copy() for m in ("momentum_12_1", "ridge", "hgb")}}


def test_dynamic_eligibility_uses_ceil_third_and_global_tie_order():
    panel = panel_fixture()
    # Eligible order deliberately differs from the frozen panel's tie order.
    r = row(panel, eligible=["DDD", "CCC", "BBB", "AAA"], scores=[1., 1., 1., 1.])
    np.testing.assert_array_equal(portfolios.weights_for(r, "ridge", panel["symbols"]), [.5, .5, 0, 0, 0])
    r = row(panel, eligible=["DDD", "CCC", "BBB"], scores=[1., 2., 3.])
    np.testing.assert_array_equal(portfolios.weights_for(r, "ridge", panel["symbols"]), [0, 1, 0, 0, 0])
    np.testing.assert_allclose(portfolios.weights_for(r, "equal_weight", panel["symbols"]), [0, 1/3, 1/3, 1/3, 0])


def test_missing_unheld_price_does_not_break_or_filter_the_portfolio():
    panel = panel_fixture(names=("AAA", "BBB", "CCC"))
    panel["series"]["CCC"]["open"] = [None] * len(panel["dates"])
    result = portfolios.simulate(panel, [row(panel)], "ridge", .0011)
    assert result["state"] == "complete"
    assert result["ledger"][0]["target_weights"] == [1., 0., 0., 0.]
    assert result["net_return"] == pytest.approx((1 - .0011) / (1 + .0011) - 1)


def test_missing_intraperiod_held_mark_is_omitted_then_resumes_without_trade():
    panel = panel_fixture(names=("AAA", "BBB", "CCC"))
    panel["series"]["AAA"]["open"][3] = None
    panel["series"]["AAA"]["open"][4] = 125.
    result = portfolios.simulate(panel, [row(panel)], "ridge", 0.)
    assert result["state"] == "complete"
    assert [p["index"] for p in result["curve"]] == [1, 2, 4, 5, 6, 7]
    assert len(result["ledger"]) == 2
    assert result["ledger"][-1]["kind"] == "liquidation"
    assert result["valuation_gaps"][0]["symbols"] == ["AAA"]
    assert result["valuation_gaps"][0]["index"] == 3
    assert next(r["equity"] for r in result["curve"] if r["index"] == 4) == pytest.approx(1.25)
    assert result["annualized_volatility"] is None
    assert result["sharpe_zero_rate"] is None
    assert result["net_return"] == pytest.approx(0.)
    assert "observed actual opens" in result["drawdown_scope"]


def test_missing_terminal_held_price_stops_exact_pnl_without_invented_sale():
    panel = panel_fixture(names=("AAA", "BBB", "CCC"))
    panel["series"]["AAA"]["open"][7] = None
    result = portfolios.simulate(panel, [row(panel)], "ridge", 0.)
    assert result["state"] == "incomplete"
    assert result["date"] == panel["dates"][7]
    assert result["unresolved_symbols"] == ["AAA"]
    assert result["held_units"] == {"AAA": .01}
    assert "net_return" not in result
    assert len(result["ledger"]) == 1


def test_missing_new_target_open_stops_even_when_it_was_not_held():
    panel = panel_fixture(names=("AAA", "BBB", "CCC"))
    first = row(panel, exit_index=4)
    second = row(panel, origin=3, scores=[1., 3., 2.])
    panel["series"]["BBB"]["open"][4] = None
    result = portfolios.simulate(panel, [first, second], "ridge", 0.)
    assert result["state"] == "incomplete"
    assert result["unresolved_symbols"] == ["BBB"]
    assert result["held_units"] == {"AAA": .01}
    assert len(result["ledger"]) == 1


def test_future_missing_history_does_not_change_current_features_or_initial_orders():
    panel = panel_fixture(n=320, names=("AAA", "BBB", "CCC"))
    t = 280
    before = Panel(panel).features(t)
    altered = copy.deepcopy(panel)
    for field in ("open", "close", "volume"):
        altered["series"]["AAA"][field][t + 2:] = [None] * (320 - t - 2)
    after = Panel(altered).features(t)
    for a, b in zip(before[:3], after[:3]):
        np.testing.assert_array_equal(a, b)
    assert before[3] == after[3]
    r = row(panel, origin=t, exit_index=302)
    old = portfolios.simulate(panel, [r], "ridge", .0011)
    new = portfolios.simulate(altered, [r], "ridge", .0011)
    assert new["state"] == "incomplete"
    assert old["ledger"][0] == new["ledger"][0]


def test_same_issuer_and_sector_concentration_are_aggregated():
    panel = panel_fixture()
    result = portfolios.simulate(panel, [row(panel)], "ridge", 0.)
    assert result["state"] == "complete"
    assert result["max_single_security_weight"] == pytest.approx(.5)
    assert result["max_issuer_weight"] == pytest.approx(1.)
    assert result["max_sector_weight"] == pytest.approx(1.)
    assert result["minimum_effective_holdings"] == pytest.approx(2.)


def test_final_partial_has_actual_endpoint_fees_and_no_fabricated_full_period():
    n = int(np.busday_count("2021-09-03", "2026-09-04")) + 1
    panel = panel_fixture(n=n, names=("AAA", "BBB", "CCC"))
    # Remove Labor Day to make the first entry the requested September 7 open.
    holiday = panel["dates"].index("2021-09-06")
    panel["dates"].pop(holiday)
    for series in panel["series"].values():
        for values in series.values():
            values.pop(holiday)
    last = len(panel["dates"]) - 1
    rows = [row(panel, origin=t, exit_index=min(t + 22, last)) for t in range(0, last - 1, 21)]
    predictions = {"metadata": {"symbols": panel["symbols"], "benchmark": "SPY"}, "rows": rows, "failures": []}
    assert portfolios.validate_rows(panel, predictions) == rows
    assert rows[-1]["truncated"] and sum(r["truncated"] for r in rows) == 1
    result = portfolios.simulate(panel, rows, "SPY", .0011)
    assert result["first_date"] == "2021-09-07"
    assert result["last_date"] == "2026-09-04"
    assert len(result["ledger"]) == 2  # Buy/hold control pays only entry and exit.
    assert result["ledger"][-1]["kind"] == "liquidation"
    assert result["ledger"][-1]["target_weights"] == [0., 0., 0., 0.]
    assert result["net_return"] == pytest.approx((1 - .0011) / (1 + .0011) - 1)
    assert math.prod(1 + r for r in result["period_returns"]) == pytest.approx(result["net_return"] + 1)
    bad = copy.deepcopy(predictions)
    bad["rows"][-1]["truncated"] = False
    with pytest.raises(ValueError, match="shortened"):
        portfolios.validate_rows(panel, bad)


def test_nonfinal_shortening_and_gap_are_rejected():
    n = int(np.busday_count("2021-09-03", "2026-09-04")) + 1
    panel = panel_fixture(n=n)
    panel["dates"][1] = "2021-09-07"  # Only boundary validation is under test here.
    last = n - 1
    rows = [row(panel, origin=t, exit_index=min(t + 22, last)) for t in range(0, last - 1, 21)]
    predictions = {"metadata": {"symbols": panel["symbols"], "benchmark": "SPY"}, "rows": rows, "failures": []}
    bad = copy.deepcopy(predictions)
    bad["rows"][0]["exit_index"] -= 1
    bad["rows"][0]["truncated"] = True
    with pytest.raises(ValueError, match="Only final"):
        portfolios.validate_rows(panel, bad)
    bad = copy.deepcopy(predictions)
    bad["rows"][1]["origin_index"] += 1
    bad["rows"][1]["entry_index"] += 1
    bad["rows"][1]["exit_index"] += 1
    with pytest.raises(ValueError, match="gap"):
        portfolios.validate_rows(panel, bad)
