from datetime import date, timedelta
from decimal import Decimal as D

import pytest

from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.data.guidance_fixture import guidance_fixture, fixture_guidance_spec
from tradingagents.research.strategies.guidance_quality import cash_quality, guidance_signal, liquidity_check


@pytest.fixture
def dataset():
    return guidance_fixture()


def notice(dataset, identifier="clean-raise"):
    return next(n for n in dataset.guidance_notices if n.notice_id == identifier)


def test_guidance_uses_original_same_period_midpoints_only_after_publication(dataset):
    current = notice(dataset)
    assert guidance_signal(dataset, current, current.availability.available_at-timedelta(seconds=1)).action == "unknown"
    signal = guidance_signal(dataset, current, current.availability.available_at)
    assert signal.action == "increase"
    assert signal.current_midpoint_usd == D("1200000000")
    assert signal.previous_midpoint_usd == D("1000000000")
    assert signal.previous_notice_id == "clean-prior"
    assert current.availability.available_at.hour == 22  # after the session close
    prior = notice(dataset, "clean-prior")
    assert guidance_signal(dataset, prior, prior.availability.available_at).action == "unknown"
    withdrawal = notice(dataset, "clean-withdrawal")
    assert guidance_signal(dataset, withdrawal, withdrawal.availability.available_at).action == "withdrawn"


def test_latest_incompatible_basis_is_not_skipped_to_find_an_increase(dataset):
    current = notice(dataset, "clean-repeat")
    notice(dataset).reporting_basis = "adjusted"
    result = guidance_signal(dataset, current, current.availability.available_at)
    assert result.action == "unknown" and result.previous_notice_id == "clean-raise"


def test_cut_and_different_forecast_period(dataset):
    current = notice(dataset)
    for observation in dataset.financials:
        if observation.observation_id == current.low_observation_id:
            observation.value = D(700)
        if observation.observation_id == current.high_observation_id:
            observation.value = D(900)
    assert guidance_signal(dataset, current, current.availability.available_at).action == "cut"
    current.period_end = date(2021, 12, 31)
    current.period_start = date(2021, 1, 1)
    assert guidance_signal(dataset, current, current.availability.available_at).action == "unknown"


def test_ttm_differences_ytd_reports_and_compares_cash_margins(dataset):
    at = notice(dataset).availability.available_at
    result = cash_quality(dataset, "sim-clean", at)
    assert result.status == "pass"
    assert result.current_revenue_usd == D("440000000")
    assert result.prior_revenue_usd == D("400000000")
    assert result.current_operating_cash_flow_usd == D("80000000")
    assert result.prior_operating_cash_flow_usd == D("40000000")
    assert result.current_cash_margin == D(80)/440
    assert len(result.observation_ids) == 16
    weak = cash_quality(dataset, "sim-weak", at)
    assert weak.status == "fail" and weak.current_operating_cash_flow_usd == -20000000


def test_missing_and_conflicting_quarters_abstain(dataset):
    at = notice(dataset).availability.available_at
    dataset.financials = [o for o in dataset.financials if o.observation_id != "clean-2019-q3-operating_cash_flow"]
    assert cash_quality(dataset, "sim-clean", at).status == "unknown"


def test_later_amendment_does_not_rewrite_past_cash_quality(dataset):
    at = notice(dataset).availability.available_at
    original = next(o for o in dataset.financials if o.observation_id == "clean-2019-q4-operating_cash_flow")
    revised = original.model_copy(deep=True)
    revised.observation_id = "amended-cash-flow"
    revised.value, revised.original_value = D(-40), "-40"
    revised.availability.available_at = at + timedelta(days=2)
    dataset.financials.append(revised)
    assert cash_quality(dataset, "sim-clean", at).status == "pass"
    assert cash_quality(dataset, "sim-clean", at+timedelta(days=2)).status == "fail"


def test_conflicting_direct_quarter_abstains(dataset):
    at = notice(dataset).availability.available_at
    annual = next(o for o in dataset.financials if o.observation_id == "clean-2019-q4-operating_cash_flow")
    direct = annual.model_copy(update={"observation_id": "direct-q4", "period_type": "quarter", "period_start": date(2019, 10, 1), "value": D(100), "original_value": "100"})
    dataset.financials.append(direct)
    assert cash_quality(dataset, "sim-clean", at).status == "unknown"


def test_stale_financials_and_illiquid_prices_do_not_pass(dataset):
    at = notice(dataset).availability.available_at
    assert cash_quality(dataset, "sim-clean", at+timedelta(days=200)).status == "unknown"
    rules = fixture_guidance_spec("guidance_control").rules
    assert liquidity_check(dataset, "sim-clean", at, rules)[0]
    for bar in dataset.bars:
        if bar.instrument_id == "sim-clean":
            bar.volume = 0
    assert not liquidity_check(dataset, "sim-clean", at, rules)[0]


def test_notice_cannot_borrow_another_issuers_numbers(dataset):
    current = notice(dataset)
    current.low_observation_id = "oneoff-raise-revenue_guidance_low"
    with pytest.raises(ValueError, match="original numeric observations disagree"):
        DatasetBundle.model_validate(dataset.model_dump(mode="json"))
