from datetime import datetime, timezone
from decimal import Decimal as D

from tradingagents.ui.brokers.alpaca import _account_activity

NOW=datetime(2026,9,4,18,tzinfo=timezone.utc)


def test_native_fill_preserves_source_identity_quantity_price_and_timestamp():
    raw={"id":"fill-1","activity_type":"FILL","symbol":"AAA","side":"buy","qty":"3","price":"100.25","order_id":"order-1","transaction_time":"2026-09-04T17:00:00Z"}
    event=_account_activity(raw,NOW)
    assert event.kind=="fill" and event.quantity==3 and event.price_usd==D("100.25")
    assert event.effective_at.hour==17 and event.time_precision=="instant"
    assert event.raw==raw and event.cash_amount_usd is None


def test_deposit_and_withdrawal_preserve_sign_and_coarse_source_date():
    for kind,code,amount in [("deposit","CSD","1000"),("withdrawal","CSW","-500")]:
        event=_account_activity({"id":kind,"activity_type":code,"date":"2026-09-04","net_amount":amount},NOW)
        assert event.kind==kind and event.cash_amount_usd==D(amount)
        assert event.time_precision=="day" and event.equity_before_flow_usd is None


def test_unverified_split_and_incomplete_cash_records_abstain_without_default_values():
    for raw in [{"id":"split","activity_type":"SPLIT","symbol":"AAA","date":"2026-09-04","qty":"2"},
                {"id":"fee","activity_type":"FEE","date":"2026-09-04"},
                {"id":"deposit","activity_type":"CSD","date":"2026-09-04","net_amount":"-100"}]:
        event=_account_activity(raw,NOW)
        assert event.kind=="unknown"
        assert event.raw==raw or event.raw["activity"]==raw
