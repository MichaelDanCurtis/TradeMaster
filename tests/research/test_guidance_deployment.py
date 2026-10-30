"""Synthetic guidance events exercise the shared prospective decision kernel."""
from datetime import datetime,timedelta,timezone
from decimal import Decimal as D

import pytest

from tradingagents.research.data.guidance_fixture import guidance_fixture,fixture_guidance_spec
from tradingagents.research.strategies.deployment_portfolio import deployment_portfolio
from tradingagents.research.strategies.guidance_deployment import GuidanceDeploymentContext


def context(**kwargs):
    return GuidanceDeploymentContext(start_at=datetime(2020,2,1,tzinfo=timezone.utc),**kwargs)


def evaluate(data,spec,at,ctx,holdings=None):
    return deployment_portfolio(data,spec,at,D(10000),holdings or {i.instrument_id:D(0) for i in spec.universe},guidance_context=ctx)


@pytest.mark.parametrize("arm,expected",[("guidance_control",{"sim-clean","sim-oneoff","sim-weak","sim-unknown"}),
    ("numeric_quality",{"sim-clean","sim-oneoff","sim-unknown"}),("astra_challenger",{"sim-clean"})])
def test_prospective_arms_use_same_shared_event_selection(arm,expected):
    data=guidance_fixture();spec=fixture_guidance_spec(arm)
    at=datetime(2020,2,10,22,2,tzinfo=timezone.utc)
    result=evaluate(data,spec,at,context())
    assert result["status"]=="targets",result["reason"]
    assert set(result["entry_notice_ids"])==expected
    assert next(r for r in result["portfolio"] if r["instrument_id"]=="sim-clean")["desired_quantity"]==19
    assert result["execution_opens_at"]==data.sessions[next(i for i,s in enumerate(data.sessions) if s.date.isoformat()=="2020-02-11")].opens_at.isoformat()


def test_actual_fill_clock_survives_repeat_and_only_exits_at_frozen_age():
    data=guidance_fixture();spec=fixture_guidance_spec("guidance_control");spec.rules.hold_sessions=5
    fill=next(s for s in data.sessions if s.date.isoformat()=="2020-02-13").opens_at+timedelta(seconds=40)
    ctx=context(holding_clocks={"sim-clean":{"notice_id":"clean-raise","entry_at":fill}},consumed_notices={"clean-raise"})
    holdings={i.instrument_id:D(19) if i.instrument_id=="sim-clean" else D(0) for i in spec.universe}
    before=evaluate(data,spec,datetime(2020,2,17,22,2,tzinfo=timezone.utc),ctx,holdings)
    assert "sim-clean" not in before["exit_reasons"] and "clean-repeat" in before["guidance_state"]["consumed_notices"]
    row=next(r for r in before["portfolio"] if r["instrument_id"]=="sim-clean")
    assert row["desired_quantity"]==19 and row["delta_quantity"]==0
    ctx.consumed_notices.update(before["guidance_state"]["consumed_notices"])
    due=evaluate(data,spec,datetime(2020,2,19,22,2,tzinfo=timezone.utc),ctx,holdings)
    assert "first actual fill" in due["exit_reasons"]["sim-clean"]
    assert next(r for r in due["portfolio"] if r["instrument_id"]=="sim-clean")["delta_quantity"]==-19


def test_withdrawal_cancels_pending_entry_without_inventing_a_fill():
    data=guidance_fixture();spec=fixture_guidance_spec("guidance_control")
    ctx=context(consumed_notices={"clean-raise"},pending_entries={"sim-clean"})
    result=evaluate(data,spec,datetime(2020,3,2,22,2,tzinfo=timezone.utc),ctx)
    assert result["status"]=="no_signal" and "sim-clean" in result["cancel_entries"]
    assert not result["portfolio"] and not result["guidance_state"]["holding_clocks"]


def test_rejected_or_expired_prepared_notice_does_not_get_another_attempt():
    data=guidance_fixture();spec=fixture_guidance_spec("guidance_control")
    ctx=context(consumed_notices={f"{name}-raise" for name in ("clean","oneoff","weak","unknown")})
    result=evaluate(data,spec,datetime(2020,2,11,22,2,tzinfo=timezone.utc),ctx)
    assert result["status"]=="no_signal" and not result["entry_notice_ids"]


def test_missing_holding_origin_or_future_calendar_pauses_instead_of_purging():
    data=guidance_fixture();spec=fixture_guidance_spec("guidance_control");at=datetime(2020,2,10,22,2,tzinfo=timezone.utc)
    holdings={i.instrument_id:D(1) if i.instrument_id=="sim-clean" else D(0) for i in spec.universe}
    result=evaluate(data,spec,at,context(),holdings)
    assert result["status"]=="unavailable" and "opening fill" in result["reason"]
    data.sessions=[s for s in data.sessions if s.date.isoformat()<="2020-02-12"]
    result=evaluate(data,spec,at,context())
    assert result["status"]=="unavailable" and "holding horizon" in result["reason"]
    assert "guidance_state" not in result
