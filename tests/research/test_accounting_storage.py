import base64
from copy import deepcopy
import json
import zlib

import pytest

from tradingagents.research.accounting_storage import encode_report, decode_report, MARKER, MAX_BYTES


def large_report():
    return {'reconciled':True, 'evidence_kind':'fixture', 'baseline_id':'baseline', 'account_key':'account',
        'equity_history':[{'observed_at':f'fixture-{i}', 'cash_usd':'123.456789', 'note':'Losses and missing observations are retained.'} for i in range(1000)],
        'discrepancies':[], 'attribution':[{'owner':'legacy_manual','period_pnl_usd':'-12.34'}]}


def test_large_report_round_trip_preserves_exact_values_and_reduces_storage():
    report=large_report();before=deepcopy(report);stored=encode_report(report)
    assert MARKER in stored
    assert len(json.dumps(stored))<len(json.dumps(report))/10
    assert decode_report(json.loads(json.dumps(stored)))==report==before
    assert stored['reconciled'] is True and stored['evidence_kind']=='fixture'


def test_legacy_and_small_reports_stay_readable_without_rewriting():
    report={'reconciled':False,'discrepancies':[{'code':'cash_mismatch'}]}
    assert MARKER not in encode_report(report)
    assert decode_report(report)==report
    assert decode_report(large_report())==large_report()


@pytest.mark.parametrize('field,value',[(MARKER,'unknown'),('sha256','0'*64),('uncompressed_bytes',1),
    ('uncompressed_bytes',MAX_BYTES+1),('uncompressed_bytes',True),('payload','not base64!'),('reconciled',False)])
def test_corrupt_or_mismatched_storage_is_rejected(field,value):
    stored=encode_report(large_report());stored[field]=value
    with pytest.raises(ValueError):decode_report(stored)


def test_truncated_trailing_or_oversized_compressed_stream_is_rejected():
    original=encode_report(large_report())
    payload=base64.b64decode(original['payload'])
    for changed in [payload[:-4],payload+b'trailing',zlib.compress(b'x'*(original['uncompressed_bytes']+20))]:
        stored=deepcopy(original);stored['payload']=base64.b64encode(changed).decode()
        with pytest.raises(ValueError):decode_report(stored)


def test_sqlite_mixed_legacy_and_compressed_reports_are_transparent_and_immutable(tmp_path):
    from datetime import timedelta
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    from tradingagents.ui.db import create_session_factory,init_db
    from tradingagents.research.accounting_models import PaperReconciliationRecord
    from tradingagents.research.accounting_repository import PaperAccountingRepository
    from tests.research.test_accounting_repository import enroll,reconciliation
    from tradingagents.ui.brokers.fake import FakePaperBroker
    from tradingagents.ui.models import now_utc
    engine,sessions=create_session_factory(f'sqlite:///{tmp_path/"mixed.db"}');init_db(engine)
    repo=PaperAccountingRepository(sessions)
    opening=FakePaperBroker(cash_usd='1000').paper_snapshot()
    opening.started_at=opening.observed_at=now_utc()-timedelta(seconds=10)
    enroll((repo,opening,''))
    first=repo.reconcile(reconciliation(opening,2,1000))
    with sessions() as session:
        record=PaperReconciliationRecord(content_hash='a'*64,account_key=first.account_key,
            request=first.request,report=large_report(),observed_at=first.observed_at+timedelta(seconds=1))
        session.add(record);session.commit();identifier=record.reconciliation_id
    with sessions() as session:
        assert session.get(PaperReconciliationRecord,first.reconciliation_id).report==first.report
        assert session.get(PaperReconciliationRecord,identifier).report==large_report()
        raw=session.execute(text('SELECT report FROM paper_account_reconciliations WHERE reconciliation_id=:id'),{'id':identifier}).scalar_one()
        assert MARKER in json.loads(raw)
        assert decode_report(json.loads(raw))==large_report()
        with pytest.raises(IntegrityError,match='immutable'):
            session.execute(text('UPDATE paper_account_reconciliations SET report=:report WHERE reconciliation_id=:id'),{'id':identifier,'report':'{}'})
    engine.dispose()
