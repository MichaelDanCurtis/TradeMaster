from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Literal, Protocol

from pydantic import AwareDatetime, Field

from tradingagents.research.contracts import Contract, CostScenario, Fraction, Identifier, StrategySpec
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.strategies.trend import TargetDecision
from tradingagents.research.strategies.guidance_portfolio import GuidanceEventDecision

Amount = Annotated[Decimal, Field(allow_inf_nan=False)]


class EngineUnavailable(RuntimeError):
    """The selected engine cannot execute these inputs; never fall back silently."""


def source_build(prefix: str) -> str:
    """Pin the actual research implementation, not just a manually bumped label."""
    import hashlib
    import decimal
    import platform
    import sys
    import pydantic
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    digest = hashlib.sha256()
    digest.update(repr((sys.version, platform.system(), platform.machine(), pydantic.__version__, decimal.__libmpdec_version__)).encode())
    for path in sorted(root.rglob("*.py")):
        digest.update(str(path.relative_to(root)).encode())
        digest.update(b"\0" + path.read_bytes() + b"\0")
    return f"{prefix}-{digest.hexdigest()}"


class ReplayRequest(Contract):
    dataset: DatasetBundle
    spec: StrategySpec
    start: date
    end: date
    initial_capital_usd: Annotated[Decimal, Field(gt=0, allow_inf_nan=False)]
    cash_annual_yield_fraction: Fraction
    scenario: CostScenario
    control: Literal["strategy", "fixed_basket", "cash", "equity_reference"] = "strategy"
    reference_allocation_fraction: Fraction = Decimal(".95")


class DecisionRecord(Contract):
    decision_id: Identifier
    at: AwareDatetime
    intended_execution_at: AwareDatetime | None
    decision: TargetDecision
    proposed_quantities: dict[str, int] = Field(default_factory=dict)
    entry_notice_ids: dict[str, str] = Field(default_factory=dict)
    exit_reasons: dict[str, str] = Field(default_factory=dict)


class Fill(Contract):
    fill_id: Identifier
    decision_id: Identifier
    instrument_id: Identifier
    signal_at: AwareDatetime
    executed_at: AwareDatetime
    observed_at: AwareDatetime
    quantity: int  # signed; a negative quantity reduces a holding
    price_usd: Amount
    fee_usd: Amount
    slippage_usd: Amount
    realized_pnl_usd: Amount


class AccountingEvent(Contract):
    at: AwareDatetime
    kind: Literal["split", "dividend", "delisting", "cash_in_lieu", "payment", "cash_yield", "unfilled", "risk_pause", "order_cancelled"]
    instrument_id: str | None = None
    amount_usd: Amount = Decimal(0)
    detail: str


class EquityPoint(Contract):
    at: AwareDatetime
    equity_usd: Amount
    cash_usd: Amount
    receivables_usd: Amount
    market_value_usd: Amount
    cost_basis_usd: Amount
    realized_pnl_usd: Amount
    unrealized_pnl_usd: Amount
    dividends_usd: Amount
    cash_yield_usd: Amount
    fees_usd: Amount
    quantities: dict[str, int]
    stale_instruments: list[str] = Field(default_factory=list)
    risk_breaches: list[str] = Field(default_factory=list)


class VenueReceipt(Contract):
    order_id: int
    decision_id: Identifier
    instrument_id: Identifier
    at: AwareDatetime
    quantity: int
    price_usd: Amount
    fee_usd: Amount
    cash_usd: Amount
    status: Literal["filled"]


class VenueEquity(Contract):
    at: AwareDatetime
    cash_usd: Amount
    equity_usd: Amount
    receivables_usd: Amount
    quantities: dict[str, int]
    cost_basis_usd: Amount


class ReplayResult(Contract):
    engine_build: Identifier
    control: Literal["strategy", "fixed_basket", "cash", "equity_reference"]
    initial_capital_usd: Amount
    decisions: list[DecisionRecord]
    fills: list[Fill]
    events: list[AccountingEvent]
    equity: list[EquityPoint]
    limitations: list[str]
    guidance_events: list[GuidanceEventDecision] = Field(default_factory=list)
    venue_receipts: list[VenueReceipt] = Field(default_factory=list)
    venue_equity: list[VenueEquity] = Field(default_factory=list)


class Engine(Protocol):
    build: str

    def run(self, request: ReplayRequest) -> ReplayResult: ...
