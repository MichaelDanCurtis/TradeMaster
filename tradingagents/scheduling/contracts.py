from datetime import timedelta
from decimal import Decimal
from typing import Annotated, Literal
from pydantic import AwareDatetime, Field, field_validator
from tradingagents.research.contracts import Contract, Identifier
from tradingagents.ui.models import now_utc


class ScheduleRequest(Contract):
    idempotency_key: Identifier
    algorithm: Literal["twap", "dca_ladder"]
    symbol: Identifier
    side: Literal["buy", "sell"]
    notional_usd: Annotated[Decimal, Field(gt=0, max_digits=14, decimal_places=2)]
    limit_price_usd: Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]
    count: Annotated[int, Field(ge=2, le=12)] = 4
    duration_minutes: Annotated[int, Field(ge=1, le=390)] = 30
    start_at: AwareDatetime = Field(default_factory=lambda: now_utc()+timedelta(seconds=30))
    span_percent: Annotated[Decimal, Field(gt=0, le=50, decimal_places=2)] = Decimal(10)

    @field_validator("symbol")
    @classmethod
    def normalized(cls, value):
        return value.strip().upper()


class ScheduleAction(Contract):
    action: Literal["approve", "pause", "resume", "stop"]
    expected_hash: str
    expected_revision: Annotated[int, Field(ge=1)]
    actor: Identifier
