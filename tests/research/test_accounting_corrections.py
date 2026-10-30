from datetime import timedelta
from decimal import Decimal as D

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from tests.research.test_accounting_repository import ledger, enroll, reconciliation, fee
from tradingagents.research.accounting_contracts import AccountActivity
from tradingagents.research.accounting_models import PaperAccountActivityRecord, PaperCorrectionApprovalRecord
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.execution_repository import account_key
from tradingagents.research.repository import ConflictError
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.models import now_utc


def revised(ledger):
    repo,opening,_=ledger;enroll(ledger)
    first=repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    request=reconciliation(opening,3,998,[fee(opening,-2)])
    latest=repo.reconcile(request)
    return first,latest,request


def approve(repo,review):
    return repo.approve_corrections(review.account_key,review.review_id,review.content_hash,"operator","Verified latest observed broker revision")


def test_review_approval_replays_corrected_event_without_mutating_old_receipts(ledger):
    repo,opening,url=ledger
    first,latest,request=revised(ledger)
    key=account_key(opening)
    review=repo.preview_corrections(key)
    assert review.payload["eligible"]
    assert review.payload["changes"][0]["previous_activity"]["cash_amount_usd"]=="-1"
    assert review.payload["changes"][0]["selected_activity"]["cash_amount_usd"]=="-2"
    assert review.payload["excluded_observation_ids"]==[first.reconciliation_id]
    assert D(review.payload["after"]["investment_pnl_usd"])==-2
    assert D(review.payload["after"]["time_weighted_return_fraction"])==D("-.002")
    assert len(repo.history(key))==2 and not repo.history(key)[0].report["reconciled"]
    accepted=approve(repo,review)
    assert approve(repo,review).correction_id==accepted.correction_id
    # Approval itself does not publish a new account observation or clear its gate.
    assert not repo.history(key)[0].report["reconciled"]
    _,sessions=create_session_factory(url);restarted=PaperAccountingRepository(sessions)
    result=restarted.reconcile(request)
    assert result.reconciliation_id!=latest.reconciliation_id and result.report["reconciled"]
    assert result.report["source_corrections"]["approval_ids"]==[accepted.correction_id]
    assert D(result.report["investment_pnl_usd"])==-2
    assert len(result.report["equity_history"])==2
    assert restarted.reconcile(request).reconciliation_id==result.reconciliation_id
    with sessions() as session:
        original=session.exec(select(PaperAccountActivityRecord)).one()
        assert original.activity["cash_amount_usd"]=="-1"
        for table in ("paper_correction_reviews","paper_correction_approvals"):
            with pytest.raises(IntegrityError,match="immutable"):
                session.execute(text(f"DELETE FROM {table}"));session.commit()
            session.rollback()
    history=restarted.history(key)
    assert any(row.reconciliation_id==first.reconciliation_id and row.report["investment_pnl_usd"]=="-1" for row in history)
    assert any(row.reconciliation_id==latest.reconciliation_id and not row.report["reconciled"] for row in history)


def test_current_balance_mismatch_cannot_be_approved_away(ledger):
    repo,opening,_=ledger;enroll(ledger)
    repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    repo.reconcile(reconciliation(opening,3,900,[fee(opening,-2)]))
    review=repo.preview_corrections(account_key(opening))
    assert not review.payload["eligible"]
    assert any(error["code"]=="cash_mismatch" for error in review.payload["discrepancies"])
    with pytest.raises(ConflictError,match="unresolved discrepancies"):approve(repo,review)


def test_unrelated_prior_discrepancy_is_not_removed_with_a_source_correction(ledger):
    repo,opening,_=ledger;enroll(ledger)
    first=repo.reconcile(reconciliation(opening,2,997,[fee(opening)]))
    repo.reconcile(reconciliation(opening,3,998,[fee(opening,-2)]))
    review=repo.preview_corrections(account_key(opening))
    assert not review.payload["eligible"] and first.reconciliation_id not in review.payload["excluded_observation_ids"]


def test_unchanged_valid_marks_are_retained(ledger):
    repo,opening,_=ledger;enroll(ledger)
    early=repo.reconcile(reconciliation(opening,.5,1000))
    first=repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    request=reconciliation(opening,3,998,[fee(opening,-2)]);repo.reconcile(request)
    review=repo.preview_corrections(account_key(opening));approve(repo,review)
    result=repo.reconcile(request)
    assert result.report["reconciled"] and len(result.report["equity_history"])==3
    assert review.payload["excluded_observation_ids"]==[first.reconciliation_id]
    assert early.observed_at.isoformat() in [point["observed_at"] for point in result.report["equity_history"]]


def test_new_revision_and_reversion_to_known_original_require_new_reviews(ledger):
    repo,opening,_=ledger
    _,_,request=revised(ledger)
    review=repo.preview_corrections(account_key(opening));approve(repo,review);repo.reconcile(request)
    third=repo.reconcile(reconciliation(opening,4,997,[fee(opening,-3)]))
    assert not third.report["reconciled"] and repo.corrections(account_key(opening))["pending_source_ids"]==["fee-1"]
    review2=repo.preview_corrections(account_key(opening));assert review2.payload["eligible"];approve(repo,review2)
    request3=reconciliation(opening,5,997,[fee(opening,-3)]);assert repo.reconcile(request3).report["reconciled"]
    reverted=repo.reconcile(reconciliation(opening,6,999,[fee(opening,-1)]))
    assert not reverted.report["reconciled"]
    # The conflict persists even if the next overlapping batch omits this event.
    missing=repo.reconcile(reconciliation(opening,7,999))
    assert not missing.report["reconciled"]
    with pytest.raises(ConflictError,match="affected source interval"):
        repo.preview_corrections(account_key(opening))
    assert repo.correction_coverage_start(account_key(opening))<fee(opening).effective_at


def test_fresh_receipt_or_competing_approval_invalidates_a_pending_review(ledger):
    repo,opening,_=ledger;_,_,request=revised(ledger)
    a=repo.preview_corrections(account_key(opening));b=repo.preview_corrections(account_key(opening))
    approve(repo,a)
    with pytest.raises(ConflictError,match="changed"):approve(repo,b)
    repo.reconcile(request)
    repo.reconcile(reconciliation(opening,4,997,[fee(opening,-3)]))
    c=repo.preview_corrections(account_key(opening))
    repo.reconcile(reconciliation(opening,5,997,[fee(opening,-3)]))
    with pytest.raises(ConflictError,match="changed"):approve(repo,c)


def test_wrong_account_hash_expiry_and_blank_reason_do_not_apply(ledger,monkeypatch):
    repo,opening,_=ledger;revised(ledger)
    review=repo.preview_corrections(account_key(opening))
    with pytest.raises(ConflictError,match="displayed"):
        repo.approve_corrections("foreign",review.review_id,review.content_hash,"operator","review")
    with pytest.raises(ConflictError,match="displayed"):
        repo.approve_corrections(review.account_key,review.review_id,"0"*64,"operator","review")
    with pytest.raises(ValueError,match="reason"):
        repo.approve_corrections(review.account_key,review.review_id,review.content_hash,"operator"," ")
    monkeypatch.setattr("tradingagents.research.accounting_repository.now_utc",lambda:review.expires_at+timedelta(seconds=1))
    with pytest.raises(ConflictError,match="changed"):approve(repo,review)
    with repo.sessions() as session:assert not session.exec(select(PaperCorrectionApprovalRecord)).all()


def test_correction_of_external_flow_does_not_fabricate_missing_flow_valuation(ledger):
    repo,opening,_=ledger;enroll(ledger)
    flow=AccountActivity(source_id="deposit",kind="deposit",cash_amount_usd=100,effective_at=opening.observed_at+timedelta(seconds=1))
    repo.reconcile(reconciliation(opening,2,1100,[flow]))
    flow=flow.model_copy(update={"cash_amount_usd":D(200)})
    request=reconciliation(opening,3,1200,[flow]);repo.reconcile(request)
    review=repo.preview_corrections(account_key(opening))
    assert review.payload["eligible"] and review.payload["after"]["time_weighted_return_fraction"] is None
    approve(repo,review);report=repo.reconcile(request).report
    assert report["reconciled"] and D(report["investment_pnl_usd"])==0 and report["time_weighted_return_fraction"] is None


def test_account_review_api_enforces_room_grants_and_exact_approval(ledger):
    from tradingagents.ui.api import create_app
    repo,opening,url=ledger;revised(ledger)
    path=f"/api/paper-accounting/accounts/{account_key(opening)}/corrections"
    with TestClient(create_app(url)) as client:
        assert client.get(path).json()["pending_source_ids"]==["fee-1"]
        assert client.post(path+"/preview",headers={"x-trademaster-room":"research"}).status_code==403
        response=client.post(path+"/preview");assert response.status_code==200
        review=response.json()
        payload={"expected_hash":review["content_hash"],"actor":"operator","reason":"Compare retained broker evidence"}
        assert client.post(path+f'/{review["review_id"]}/approve',json=payload,headers={"x-trademaster-room":"research"}).status_code==403
        accepted=client.post(path+f'/{review["review_id"]}/approve',json=payload)
        assert accepted.status_code==200 and client.get(path).json()["pending_source_ids"]==[]


def test_reversion_restores_old_marks_that_reconcile_again(ledger):
    repo,opening,_=ledger
    first,_,request=revised(ledger)
    approve(repo,repo.preview_corrections(account_key(opening)));corrected=repo.reconcile(request)
    reverted=reconciliation(opening,4,999,[fee(opening)]);repo.reconcile(reverted)
    review=repo.preview_corrections(account_key(opening))
    assert review.payload["eligible"] and first.reconciliation_id in review.payload["restored_observation_ids"]
    assert first.reconciliation_id not in review.payload["excluded_observation_ids"]
    assert corrected.reconciliation_id in review.payload["excluded_observation_ids"]
    approve(repo,review);report=repo.reconcile(reverted).report
    assert report["reconciled"] and D(report["investment_pnl_usd"])==-1
    assert first.observed_at.isoformat() in [point["observed_at"] for point in report["equity_history"]]


def test_conflicting_same_time_snapshots_cannot_be_hidden_by_correction(ledger):
    repo,opening,_=ledger;enroll(ledger)
    # The original source selection matches the last same-time mark but there
    # are incompatible broker snapshots. This conflict is not a fee correction.
    repo.reconcile(reconciliation(opening,2,998,[fee(opening)]))
    repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    repo.reconcile(reconciliation(opening,3,998,[fee(opening,-2)]))
    review=repo.preview_corrections(account_key(opening))
    assert not review.payload["eligible"] and not review.payload["excluded_observation_ids"]
    assert any(error["code"]=="conflicting_account_snapshot" for error in review.payload["discrepancies"])
