"""Account reporting precision, separate from cash-ledger and quantity tolerances."""
from decimal import Decimal, ROUND_HALF_UP

MICRO_USD = Decimal("0.000001")
CENT = Decimal("0.01")


def equity_residual(snapshot):
    return snapshot.equity_usd - snapshot.cash_usd - sum(
        (p.market_value_usd for p in snapshot.positions), Decimal(0))


def equity_reconciles(snapshot):
    residual = equity_residual(snapshot)
    if abs(residual) <= MICRO_USD:
        return True
    # Only Alpaca's USD account summary is cent-reported. Preserve its raw
    # detailed marks; never apply this allowance to cash, fills, or other sources.
    if snapshot.provider_id != "alpaca-paper-broker" or snapshot.evidence_kind != "broker_paper":
        return False
    detailed = snapshot.equity_usd - residual
    return (snapshot.equity_usd == snapshot.equity_usd.quantize(CENT)
            and detailed.quantize(CENT, rounding=ROUND_HALF_UP) == snapshot.equity_usd)


def rounding_record(snapshot):
    return {"observed_at": snapshot.observed_at.isoformat(),
            "reported_equity_usd": snapshot.equity_usd,
            "detailed_equity_usd": snapshot.equity_usd - equity_residual(snapshot),
            "reporting_residual_usd": equity_residual(snapshot),
            "accepted": equity_reconciles(snapshot)}
