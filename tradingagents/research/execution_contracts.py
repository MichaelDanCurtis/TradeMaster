"""Exact paper orders and observed account facts, shared by manual and strategy orders."""
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from tradingagents.research.contracts import Contract, Fraction, Identifier, Money, PositiveMoney

Quantity = Annotated[Decimal, Field(ge=0, max_digits=24, decimal_places=9, allow_inf_nan=False)]
OrderStatus = Literal["accepted", "new", "partially_filled", "filled", "canceled", "expired", "rejected", "pending_cancel", "pending_new", "unknown"]
TERMINAL = {"filled", "canceled", "expired", "rejected"}


class AccountPosition(Contract):
    symbol: Identifier
    quantity: Quantity
    market_value_usd: Money
    cost_basis_usd: Money
    risk_group: Identifier | None = None


class OpenPaperOrder(Contract):
    client_order_id: Identifier
    broker_order_id: Identifier
    symbol: Identifier
    side: Literal["buy", "sell"]
    remaining_quantity: Quantity
    maximum_price_usd: PositiveMoney | None
    risk_group: Identifier | None = None


class PaperAccountIdentity(Contract):
    provider_id: Identifier
    account_id: Identifier
    environment: Literal["paper"] = "paper"


class PaperAccountSnapshot(PaperAccountIdentity):
    evidence_kind: Literal["broker_paper", "fixture"]
    started_at: AwareDatetime
    observed_at: AwareDatetime
    equity_usd: Money
    cash_usd: Money
    buying_power_usd: Money
    daily_turnover_usd: Money
    drawdown_fraction: Fraction | None
    currency: Literal["USD"] = "USD"
    trading_blocked: bool
    positions: list[AccountPosition]
    open_orders: list[OpenPaperOrder]
    complete: bool
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check(self):
        if self.started_at > self.observed_at:
            raise ValueError("account observation precedes its request")
        if len({p.symbol for p in self.positions}) != len(self.positions):
            raise ValueError("account positions contain duplicate symbols")
        if len({o.client_order_id for o in self.open_orders}) != len(self.open_orders):
            raise ValueError("account orders contain duplicate client IDs")
        return self


class ExactPaperOrder(Contract):
    symbol: Identifier
    side: Literal["buy", "sell"]
    quantity: Annotated[int, Field(gt=0, le=1_000_000_000)]
    limit_price_usd: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]
    fee_reserve_usd: Money = Decimal(0)
    order_type: Literal["limit"] = "limit"
    time_in_force: Literal["day", "gtc"] = "day"
    risk_group: Identifier | None = None
    stop_loss_usd: PositiveMoney | None = None
    take_profit_usd: PositiveMoney | None = None
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def check(self):
        if self.symbol != self.symbol.upper():
            raise ValueError("order symbol must be normalized")
        if self.stop_loss_usd is not None or self.take_profit_usd is not None:
            for price in (self.stop_loss_usd, self.take_profit_usd):
                if price is not None and price != price.quantize(Decimal(".01")):
                    raise ValueError("protective prices must use whole USD cents; approval cannot silently round them")
            if self.side != "buy":
                raise ValueError("protective entry legs require a long buy; reductions use a plain limit order")
            if self.stop_loss_usd is not None and self.stop_loss_usd >= self.limit_price_usd:
                raise ValueError("protective stop must be below the entry limit")
            if self.take_profit_usd is not None and self.take_profit_usd <= self.limit_price_usd:
                raise ValueError("take profit must exceed the entry limit")
        return self

    @property
    def maximum_notional_usd(self) -> Decimal:
        return self.quantity * self.limit_price_usd


class ExecutionPolicy(Contract):
    max_position_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    max_group_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    max_turnover_fraction: Annotated[Decimal, Field(gt=0, le=2)]
    max_drawdown_fraction: Fraction
    cash_reserve_fraction: Fraction = Decimal(0)
    snapshot_max_age_seconds: Annotated[int, Field(ge=1, le=60)] = 15
    allow_risk_reductions_during_drawdown: Literal[True] = True


class PaperOrderObservation(Contract):
    client_order_id: Identifier
    broker_order_id: Identifier
    symbol: Identifier
    side: Literal["buy", "sell"]
    quantity: Annotated[int, Field(gt=0)]
    filled_quantity: Quantity
    average_fill_price_usd: PositiveMoney | None
    status: OrderStatus
    observed_at: AwareDatetime
    broker_updated_at: AwareDatetime | None = None
    raw: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def check(self):
        if self.filled_quantity > self.quantity:
            raise ValueError("filled quantity exceeds the order")
        if self.status == "filled" and self.filled_quantity != self.quantity:
            raise ValueError("filled status requires the entire quantity")
        if self.filled_quantity and self.average_fill_price_usd is None:
            raise ValueError("a fill requires its observed price")
        return self
