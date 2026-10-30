from datetime import timedelta
from decimal import Decimal as D

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from tradingagents.research.accounting_contracts import AccountActivity, AccountActivityBatch, AccountingReconciliation
from tradingagents.research.accounting_models import PaperAccountActivityRecord, PaperActivityRevisionRecord
from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.execution_contracts import AccountPosition
from tradingagents.research.execution_repository import account_key
from tradingagents.research.repository import ConflictError
from tradingagents.ui.brokers.fake import FakePaperBroker
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.models import now_utc


@pytest.fixture
def ledger(tmp_path):
    url=f"sqlite:///{tmp_path/'ledger.db'}"
    engine,sessions=create_session_factory(url);init_db(engine)
    repo=PaperAccountingRepository(sessions)
    opening=FakePaperBroker(cash_usd="1000").paper_snapshot()
    opening.started_at=opening.observed_at=now_utc()-timedelta(seconds=10)
    return repo,opening,url


def enroll(ledger):
    repo,opening,_=ledger
    preview=repo.preview_baseline(opening)
    return repo.approve_baseline(preview.baseline_id,preview.content_hash,"operator")


def reconciliation(opening, second, cash, activities=(), *, start=0, complete=True, positions=None):
    observed=opening.observed_at+timedelta(seconds=second)
    positions=positions or []
    snap=opening.model_copy(update={"started_at":observed,"observed_at":observed,"cash_usd":D(cash),"equity_usd":D(cash)+sum((p.market_value_usd for p in positions),D(0)),"positions":positions})
    batch=AccountActivityBatch(provider_id=opening.provider_id,account_id=opening.account_id,evidence_kind="fixture",coverage_start=opening.observed_at+timedelta(seconds=start),coverage_end=observed,observed_at=now_utc(),complete=complete,source="fixture",activities=list(activities))
    return AccountingReconciliation(snapshot=snap,batch=batch)


def fee(opening, amount=-1):
    return AccountActivity(source_id="fee-1",kind="fee",cash_amount_usd=amount,effective_at=opening.observed_at+timedelta(seconds=1))


def test_baseline_requires_exact_approval_and_cannot_reset_account_history(ledger):
    repo,opening,_=ledger
    preview=repo.preview_baseline(opening)
    with pytest.raises(ConflictError,match="displayed account"):
        repo.approve_baseline(preview.baseline_id,"0"*64,"operator")
    enrollment=repo.approve_baseline(preview.baseline_id,preview.content_hash,"operator")
    assert repo.approve_baseline(preview.baseline_id,preview.content_hash,"operator").baseline_id==enrollment.baseline_id
    with pytest.raises(ConflictError,match="already has"):
        repo.preview_baseline(opening)
    with repo.sessions() as session:
        with pytest.raises(IntegrityError,match="immutable"):
            session.execute(text("UPDATE paper_account_enrollments SET actor='replacement'"));session.commit()


def test_idempotent_activity_import_and_equity_history_survive_restart(ledger):
    repo,opening,url=ledger;enroll(ledger)
    request=reconciliation(opening,2,999,[fee(opening)])
    first=repo.reconcile(request)
    assert first.report["reconciled"] and first.report["investment_pnl_usd"]=="-1"
    assert repo.reconcile(request).reconciliation_id==first.reconciliation_id
    _,sessions=create_session_factory(url);restarted=PaperAccountingRepository(sessions)
    # The next receipt overlaps the prior period; source identity deduplicates.
    second=restarted.reconcile(reconciliation(opening,3,999,[fee(opening)]))
    assert len(second.report["equity_history"])==3
    with sessions() as session:
        assert len(session.exec(select(PaperAccountActivityRecord)).all())==1
        with pytest.raises(IntegrityError,match="immutable"):
            session.execute(text("DELETE FROM paper_account_activities"));session.commit()
    assert restarted.list_accounts()[0]["latest"].reconciliation_id==second.reconciliation_id


def test_reconciliation_replays_sources_without_loading_cumulative_old_reports(ledger):
    from sqlalchemy import event
    repo,opening,_=ledger;enroll(ledger)
    first=repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    statements=[];engine=repo.sessions.kw['bind']
    def capture(conn,cursor,statement,parameters,context,executemany):
        statements.append(statement)
    event.listen(engine,'before_cursor_execute',capture)
    try:
        second=repo.reconcile(reconciliation(opening,3,999,[fee(opening)]))
        assert repo.latest_observed_at(account_key(opening))==second.observed_at
        assert repo.correction_coverage_start(account_key(opening)) is None
    finally:
        event.remove(engine,'before_cursor_execute',capture)
    replay_reads=[s for s in statements if s.startswith('SELECT') and 'FROM paper_account_reconciliations' in s
        and 'WHERE paper_account_reconciliations.account_key' in s and 'LIMIT' not in s]
    assert replay_reads
    assert all('paper_account_reconciliations.report' not in s for s in replay_reads)
    assert second.report['reconciled'] and second.report['investment_pnl_usd']=='-1'
    assert len(second.report['equity_history'])==3
    # Deferred reads neither erase nor replace any historical calculated receipt.
    assert next(r for r in repo.history(account_key(opening)) if r.reconciliation_id==first.reconciliation_id).report==first.report


def test_missing_then_arriving_fill_reconciles_prior_observation_without_rewriting_it(ledger):
    repo,opening,_=ledger;enroll(ledger)
    positions=[AccountPosition(symbol="AAA",quantity=2,cost_basis_usd=200,market_value_usd=200)]
    first=repo.reconcile(reconciliation(opening,2,800,positions=positions))
    assert not first.report["reconciled"] and first.report["investment_pnl_usd"] is None
    fill=AccountActivity(source_id="fill-1",kind="fill",symbol="AAA",side="buy",quantity=2,price_usd=100,broker_order_id="external",effective_at=opening.observed_at+timedelta(seconds=1))
    second=repo.reconcile(reconciliation(opening,3,800,[fill],positions=positions))
    assert second.report["reconciled"] and second.report["investment_pnl_usd"]=="0"
    assert all(point["time_weighted_return_fraction"]=="0" for point in second.report["equity_history"])
    assert not repo.history(account_key(opening))[-1].report["reconciled"]


def test_conflicting_source_revision_is_preserved_and_blocks_return_claims(ledger):
    repo,opening,_=ledger;enroll(ledger)
    repo.reconcile(reconciliation(opening,2,999,[fee(opening)]))
    corrected=repo.reconcile(reconciliation(opening,3,998,[fee(opening,-2)]))
    assert not corrected.report["reconciled"] and corrected.report["time_weighted_return_fraction"] is None
    assert corrected.report["unexplained_equity_change_usd"] == "-2"
    assert any(x["code"]=="source_activity_revised" for x in corrected.report["discrepancies"])
    with repo.sessions() as session:
        assert len(session.exec(select(PaperActivityRevisionRecord)).all())==1


def test_incremental_coverage_must_connect_to_the_reviewed_baseline(ledger):
    repo,opening,_=ledger;enroll(ledger)
    gap=repo.reconcile(reconciliation(opening,2,1000,start=1))
    assert not gap.report["reconciled"]
    full=repo.reconcile(reconciliation(opening,3,1000,start=0))
    assert full.report["reconciled"]
    incremental=repo.reconcile(reconciliation(opening,4,1000,start=3))
    assert incremental.report["reconciled"] and len(incremental.report["equity_history"])==4


def test_stale_or_unreconciled_opening_balances_cannot_be_approved(ledger):
    repo,opening,_=ledger
    with pytest.raises(ConflictError,match="fresh"):
        repo.preview_baseline(opening.model_copy(update={"started_at":now_utc()-timedelta(minutes=2)}))
    with pytest.raises(ConflictError,match="do not reconcile"):
        repo.preview_baseline(opening.model_copy(update={"equity_usd":D(2000)}))


def test_source_formatting_changes_are_retained_without_false_economic_revisions(ledger):
    repo,opening,_=ledger;enroll(ledger)
    first=fee(opening).model_copy(update={"raw":{"net_amount":"-1"}})
    repo.reconcile(reconciliation(opening,2,999,[first]))
    formatted=fee(opening).model_copy(update={"cash_amount_usd":D("-1.00"),"raw":{"net_amount":"-1.00","retrieval_note":"new read"}})
    result=repo.reconcile(reconciliation(opening,3,999,[formatted]))
    assert result.report["reconciled"]
    assert result.request["batch"]["activities"][0]["raw"]["retrieval_note"]=="new read"
    assert len(result.report["calculation_build"])==64
    with repo.sessions() as session:
        assert not session.exec(select(PaperActivityRevisionRecord)).all()


def test_baseline_accepts_alpaca_cent_reporting_but_retains_original_snapshot(ledger):
    repo, opening, _ = ledger
    opening.provider_id = "alpaca-paper-broker"
    opening.evidence_kind = "broker_paper"
    opening.positions = [AccountPosition(symbol="AAA", quantity=2, cost_basis_usd=800, market_value_usd="821.855771")]
    opening.equity_usd = D("1821.86")
    preview = repo.preview_baseline(opening)
    assert preview.snapshot["equity_usd"] == "1821.86"
    assert preview.snapshot["positions"][0]["market_value_usd"] == "821.855771"
    opening.equity_usd += D(".01")
    with pytest.raises(ConflictError, match="reconcile"):
        repo.preview_baseline(opening)
