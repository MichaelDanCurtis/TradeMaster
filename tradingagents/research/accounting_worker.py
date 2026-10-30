"""Bounded account reconciliation cycles; no new-order submission authority."""
import argparse
import json
import time

from tradingagents.research.accounting_repository import PaperAccountingRepository
from tradingagents.research.accounting_service import reconcile_paper_account
from tradingagents.research.execution_repository import account_key
from tradingagents.ui.db import create_session_factory, init_db


def reconcile_configured_account(sessions, broker):
    accounting = PaperAccountingRepository(sessions)
    identity = broker.paper_identity() if callable(getattr(broker,"paper_identity",None)) else broker.paper_snapshot()
    key = account_key(identity)
    if accounting.baseline(key) is None:
        return {"status":"baseline_review_required", "account_key":key}
    receipt = reconcile_paper_account(broker, accounting, key)
    return {"status":"reconciled" if receipt.report["reconciled"] else "needs_attention", "account_key":key,
        "reconciliation_id":receipt.reconciliation_id, "observed_at":receipt.observed_at.isoformat(),
        "drawdown_available":receipt.report["drawdown_fraction"] is not None}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url",required=True)
    parser.add_argument("--once",action="store_true")
    parser.add_argument("--interval-seconds",type=int,default=60)
    args=parser.parse_args()
    if not 15 <= args.interval_seconds <= 86400: parser.error("interval must be between 15 and 86400 seconds")
    engine,sessions=create_session_factory(args.database_url);init_db(engine)
    from tradingagents.ui.api import _resolve_broker_adapter
    from tradingagents.ui.repository import UiRepository
    try:
        while True:
            try:
                result=reconcile_configured_account(sessions,_resolve_broker_adapter(UiRepository(sessions),{}))
            except Exception as exc:
                result={"status":"unavailable", "error_type":type(exc).__name__, "message":"Account observation failed; no order was submitted"}
            print(json.dumps(result),flush=True)
            if args.once: return
            time.sleep(args.interval_seconds)
    except KeyboardInterrupt:
        return


if __name__=="__main__": main()
