from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from decimal import Decimal as D

import pytest

from tests.research.test_guidance_replay import request
from tradingagents.research.data.contracts import CorporateAction
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.engines.replay import LocalReplayEngine
from tradingagents.research.evaluation.paired_events import attribute_events, paired_events, save_paired_events, verify_paired_artifacts


def test_paired_notices_keep_exclusions_repeats_cash_and_actual_trade_pnl():
    left_request=request("astra_challenger");right_request=request("numeric_quality")
    left_request.cash_annual_yield_fraction=right_request.cash_annual_yield_fraction=D(".03")
    engine=LocalReplayEngine()
    left,right=engine.run(left_request),engine.run(right_request)
    summary,rows=paired_events(left_request.dataset,left_request.spec,left,right,start=left_request.start,end=left_request.end)
    oneoff=next(row for row in rows if row["notice_id"]=="oneoff-raise")
    assert not oneoff["challenger"]["entered"] and oneoff["challenger"]["investment_pnl_usd"]=="0"
    assert oneoff["control"]["entered"] and oneoff["control"]["fills"]
    assert any(event["evidence_verdict"]=="exclude" for event in oneoff["challenger"]["decisions"])
    clean=next(row for row in rows if row["notice_id"]=="clean-raise")
    repeat=next(row for row in rows if row["notice_id"]=="clean-repeat")
    assert clean["cluster_id"]==repeat["cluster_id"]
    assert repeat["challenger"]["investment_pnl_usd"]=="0" and not repeat["challenger"]["entered"]
    assert any(event["status"]=="already_held" for event in repeat["challenger"]["decisions"])
    assert summary["both_entered"]==1 and summary["control_only"]==2
    assert sum(D(row["pnl_difference_usd"]) for row in rows)==D(summary["event_pnl_difference_usd"])
    assert D(summary["cash_yield_difference_usd"])!=0
    assert abs(D(summary["event_pnl_difference_usd"])+D(summary["cash_yield_difference_usd"])-D(summary["portfolio_pnl_difference_usd"]))<D(".00000001")
    assert abs(D(summary["portfolio_pnl_difference_usd"])-(left.equity[-1].equity_usd-right.equity[-1].equity_usd))<D(".00000001")


def test_fractional_split_dividend_and_unpaid_delisting_follow_entry_notice():
    req=request("astra_challenger")
    sessions={s.date:s for s in req.dataset.sessions}
    for bar in req.dataset.bars:
        if bar.instrument_id=="sim-clean" and bar.session>=date(2020,2,11):
            price=D(100) if bar.session==date(2020,2,11) else D(60)
            bar.open=bar.high=bar.low=bar.close=price
    req.dataset.actions=[
        CorporateAction(action_id="fractional",instrument_id="sim-clean",kind="split",effective_session=date(2020,2,12),available_at=sessions[date(2020,2,12)].opens_at,split_ratio="1.5"),
        CorporateAction(action_id="entitled-income",instrument_id="sim-clean",kind="dividend",effective_session=date(2020,2,13),available_at=sessions[date(2020,2,13)].opens_at,cash_per_share_usd=1,payable_at=None),
        CorporateAction(action_id="cash-exit",instrument_id="sim-clean",kind="delisting",effective_session=date(2020,2,14),available_at=sessions[date(2020,2,14)].opens_at,cash_per_share_usd=70,payable_at=None),
    ]
    run=LocalReplayEngine().run(req)
    book=attribute_events(req.dataset,req.spec,run)["outcomes"]["clean-raise"]
    assert len(book["fills"])==1 and book["fills"][0]["quantity"]==19
    # Buy 19 at 100.05 plus $1; .5 share paid at $60; $28 dividend;
    # 28 shares delisted for $70, still receivable rather than spendable cash.
    assert D(book["investment_pnl_usd"])==D("116.05")
    assert D(book["dividends_usd"])==28 and D(book["fees_usd"])==1
    assert D(book["corporate_actions"][0]["cash_in_lieu_usd"])==30
    assert book["state"]=="closed" and book["remaining_quantity"]==0
    assert run.equity[-1].receivables_usd==1988
    assert run.equity[-1].equity_usd-10000==D(book["investment_pnl_usd"])


def test_unfilled_entry_retains_proposal_and_does_not_invent_a_return():
    req=request("astra_challenger")
    req.dataset.bars=[b for b in req.dataset.bars if not (b.instrument_id=="sim-clean" and b.session==date(2020,2,11))]
    req.dataset.guidance_notices=[n for n in req.dataset.guidance_notices if not n.notice_id.endswith("-repeat")]
    run=LocalReplayEngine().run(req)
    outcome=attribute_events(req.dataset,req.spec,run)["outcomes"]["clean-raise"]
    assert outcome["entry_proposed"] and outcome["state"]=="not_filled"
    assert not outcome["fills"] and outcome["investment_pnl_usd"]=="0"


def test_open_event_keeps_unrealized_pnl_and_explicit_stale_mark():
    req=request("astra_challenger");req.end=date(2020,3,27)
    req.dataset.bars=[b for b in req.dataset.bars if not (b.instrument_id=="sim-clean" and b.session>=date(2020,3,3))]
    run=LocalReplayEngine().run(req)
    outcome=attribute_events(req.dataset,req.spec,run)["outcomes"]["clean-raise"]
    assert outcome["state"]=="open" and outcome["final_valuation_stale"]
    assert outcome["remaining_quantity"]==19 and outcome["exit_at"] is None and outcome["stale_closes"]>0
    assert D(outcome["investment_pnl_usd"])==run.equity[-1].equity_usd-run.initial_capital_usd


def test_forged_sale_or_holdings_cannot_produce_reconciled_pairs():
    req=request("astra_challenger");run=LocalReplayEngine().run(req)
    run.fills[-1].realized_pnl_usd+=1
    with pytest.raises(ValueError,match="sale basis"):
        attribute_events(req.dataset,req.spec,run)
    run=LocalReplayEngine().run(req)
    run.equity[-1].quantities["sim-clean"]=1
    with pytest.raises(ValueError,match="holdings"):
        attribute_events(req.dataset,req.spec,run)


def test_paired_artifact_pagination_preserves_every_row_and_hash(tmp_path):
    req=request("astra_challenger");run=LocalReplayEngine().run(req)
    summary,rows=paired_events(req.dataset,req.spec,run,run,start=req.start,end=req.end)
    # Exercise page boundaries independently of strategy-event sample size.
    many=[{**rows[0],"notice_id":f"page-row-{index}"} for index in range(101)]
    store=ArtifactStore(tmp_path)
    summary["events"]=len(many)
    saved,hashes=save_paired_events(store,summary,many,{"scenario":"pagination fixture"})
    index=store.json(saved.artifact_hash)
    assert [page["rows"] for page in index["pages"]]==[50,50,1]
    assert saved.page_artifact_hashes==[page["artifact_hash"] for page in index["pages"]]
    assert all(digest in hashes for digest in saved.page_artifact_hashes)
    assert [row for page in index["pages"] for row in store.json(page["artifact_hash"])["rows"]]==many


def test_publication_rejects_missing_or_inconsistent_event_pages(tmp_path):
    req=request("astra_challenger");run=LocalReplayEngine().run(req)
    summary,rows=paired_events(req.dataset,req.spec,run,run,start=req.start,end=req.end)
    store=ArtifactStore(tmp_path);run_hash=store.put_json(run)
    saved,hashes=save_paired_events(store,summary,rows,{"challenger_version_id":"v","control_version_id":"v","scenario":"base",
        "challenger_run_hash":run_hash,"control_run_hash":run_hash})
    report={"runs":[{"version_id":"v","scenario":"base","control":"strategy","artifact_hash":run_hash}],
        "arm_comparisons":[{"challenger_version_id":"v","control_version_id":"v","scenario":"base","paired_events":saved.model_dump(mode="json")}]}
    artifacts={str(index):digest for index,digest in enumerate([run_hash,*hashes])}
    verify_paired_artifacts(report,artifacts,store)
    with pytest.raises(ValueError,match="missing"):
        verify_paired_artifacts(report,{key:digest for key,digest in artifacts.items() if digest!=saved.page_artifact_hashes[0]},store)
    index=store.json(saved.artifact_hash);index["pages"][0]["offset"]=1
    replacement=store.put_json(index)
    report["arm_comparisons"][0]["paired_events"]["artifact_hash"]=replacement
    with pytest.raises(ValueError,match="coverage"):
        verify_paired_artifacts(report,{**artifacts,"replacement":replacement},store)


def test_notice_window_uses_declared_calendar_date_across_utc_midnight():
    req=request("astra_challenger");run=LocalReplayEngine().run(req)
    notice=req.dataset.guidance_notices[-1].model_copy(deep=True)
    notice.notice_id="last-local-evening"
    notice.availability.available_at=datetime(2020,4,30,23,tzinfo=ZoneInfo(req.dataset.timezone)).astimezone(timezone.utc)
    assert notice.availability.available_at.date()>req.end
    req.dataset.guidance_notices.append(notice)
    summary,rows=paired_events(req.dataset,req.spec,run,run,start=req.start,end=req.end)
    row=next(row for row in rows if row["notice_id"]==notice.notice_id)
    assert not row["challenger"]["entered"] and row["pnl_difference_usd"]=="0" and summary["reconciled"]
