"""Observed USD paper-account activity; unknown data stays unknown."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from tradingagents.research.contracts import Contract, Identifier, PositiveMoney
from tradingagents.research.execution_contracts import PaperAccountIdentity, PaperAccountSnapshot, PaperOrderObservation, Quantity

Amount = Annotated[Decimal, Field(max_digits=30, decimal_places=9, allow_inf_nan=False)]


class AccountActivity(Contract):
    source_id: Identifier
    kind: Literal["fill", "deposit", "withdrawal", "dividend", "interest", "fee", "split", "cash_in_lieu", "symbol_change", "unknown"]
    effective_at: AwareDatetime
    time_precision: Literal["instant", "day"] = "instant"
    symbol: Identifier | None = None
    side: Literal["buy", "sell"] | None = None
    quantity: Quantity | None = None
    price_usd: PositiveMoney | None = None
    cash_amount_usd: Amount | None = None
    fee_usd: Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6)] = Decimal(0)
    broker_order_id: Identifier | None = None
    split_ratio: Annotated[Decimal, Field(gt=0, le=1000000, allow_inf_nan=False)] | None = None
    new_symbol: Identifier | None = None
    entitlement_at: AwareDatetime | None = None
    equity_before_flow_usd: PositiveMoney | None = None
    flow_valuation_reference: Identifier | None = None
    raw: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_kind(self):
        if self.kind == "fill":
            if not (self.symbol and self.side and self.quantity and self.price_usd and self.broker_order_id):
                raise ValueError("fill needs symbol, side, positive quantity/price and broker order ID")
            if self.cash_amount_usd is not None:
                raise ValueError("fill cash is derived from quantity/price and fee, never counted twice")
        elif self.kind in {"deposit", "withdrawal", "dividend", "interest", "fee", "cash_in_lieu"}:
            if self.cash_amount_usd is None or self.cash_amount_usd == 0:
                raise ValueError("cash activity needs an observed nonzero signed amount")
            if self.kind in {"deposit", "dividend", "cash_in_lieu"} and self.cash_amount_usd < 0:
                raise ValueError("cash credit must be positive")
            if self.kind in {"withdrawal", "fee"} and self.cash_amount_usd > 0:
                raise ValueError("cash debit must be negative")
            if self.kind == "cash_in_lieu" and not (self.symbol and self.quantity):
                raise ValueError("cash-in-lieu needs the removed fractional quantity")
        elif self.kind == "split" and not (self.symbol and self.split_ratio):
            raise ValueError("split needs a symbol and positive ratio")
        elif self.kind == "symbol_change" and not (self.symbol and self.new_symbol and self.symbol != self.new_symbol):
            raise ValueError("symbol change needs distinct original and replacement symbols")
        if self.kind != "fill" and self.fee_usd:
            raise ValueError("standalone fees use a separate signed fee activity")
        if self.equity_before_flow_usd is not None or self.flow_valuation_reference is not None:
            if self.kind not in {"deposit", "withdrawal"} or self.time_precision != "instant" or not (self.equity_before_flow_usd and self.flow_valuation_reference):
                raise ValueError("flow valuation needs an exact external-flow timestamp, equity and source reference")
        if self.entitlement_at is not None and (self.kind != "dividend" or self.entitlement_at > self.effective_at):
            raise ValueError("dividend entitlement must be on or before payment")
        return self


class AccountActivityBatch(PaperAccountIdentity):
    coverage_start: AwareDatetime
    coverage_end: AwareDatetime
    observed_at: AwareDatetime
    complete: bool
    source: Identifier
    evidence_kind: Literal["broker_paper", "fixture"]
    activities: list[AccountActivity] = Field(max_length=20000)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check(self):
        if not self.coverage_start <= self.coverage_end <= self.observed_at:
            raise ValueError("activity coverage must precede observation")
        if len({a.source_id for a in self.activities}) != len(self.activities):
            raise ValueError("activity batch contains duplicate source IDs")
        return self


class ProtectiveChild(Contract):
    role: Literal["stop_loss", "take_profit"]
    observation: PaperOrderObservation
    limit_price_usd: PositiveMoney | None = None
    stop_price_usd: PositiveMoney | None = None


class AccountOrderFamily(Contract):
    parent: PaperOrderObservation
    children: list[ProtectiveChild] = Field(max_length=2)

    @model_validator(mode="after")
    def check(self):
        ids = [self.parent.broker_order_id]+[child.observation.broker_order_id for child in self.children]
        clients = [self.parent.client_order_id]+[child.observation.client_order_id for child in self.children]
        if len(set(ids)) != len(ids) or len(set(clients)) != len(clients):
            raise ValueError("Order family repeats a parent or child identity")
        if len({child.role for child in self.children}) != len(self.children):
            raise ValueError("Order family repeats a protective role")
        for child in self.children:
            leg = child.observation
            if self.parent.side != "buy" or leg.side != "sell" or leg.symbol != self.parent.symbol or leg.quantity > self.parent.quantity:
                raise ValueError("Protective child must reduce the parent's long position")
            if child.role == "stop_loss" and child.stop_price_usd is None:
                raise ValueError("Protective stop requires its observed trigger price")
            if child.role == "take_profit" and child.limit_price_usd is None:
                raise ValueError("Take profit requires its observed limit price")
        return self


class AccountingReconciliation(Contract):
    snapshot: PaperAccountSnapshot
    batch: AccountActivityBatch
    order_families: list[AccountOrderFamily] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def check(self):
        if (self.snapshot.provider_id, self.snapshot.account_id, self.snapshot.evidence_kind) != (self.batch.provider_id, self.batch.account_id, self.batch.evidence_kind):
            raise ValueError("activity coverage belongs to a different account or evidence class")
        if self.batch.coverage_end < self.snapshot.observed_at:
            raise ValueError("activity coverage ends before the account snapshot")
        ids = [family.parent.broker_order_id for family in self.order_families]
        if len(set(ids)) != len(ids):
            raise ValueError("Account observation repeats an order family")
        return self
