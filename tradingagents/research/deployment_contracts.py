"""Paper deployment requests never carry lifecycle or order authority."""
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, Field, model_validator
from typing import Annotated

from tradingagents.research.contracts import Contract, Digest, Identifier, Money, PositiveMoney, Text
from tradingagents.research.execution_contracts import ExecutionPolicy, PaperAccountIdentity


class DeploymentTerms(Contract):
    capital_usd: PositiveMoney
    execution_policy: ExecutionPolicy
    fee_reserve_per_order_usd: Money
    fee_assumption_reference: Text
    funding_rationale: Text
    per_order_human_approval: Literal[True] = True

    @model_validator(mode="after")
    def check(self):
        if self.execution_policy.max_position_fraction > self.execution_policy.max_group_fraction:
            raise ValueError("Deployment position cap cannot exceed its group cap")
        if self.execution_policy.max_drawdown_fraction <= 0 or self.execution_policy.cash_reserve_fraction >= 1:
            raise ValueError("Deployment needs a positive drawdown limit and investable capital")
        if self.fee_reserve_per_order_usd >= self.capital_usd:
            raise ValueError("Fee reserve must leave investable capital")
        return self


class DeploymentInput(Contract):
    name: Identifier
    version_id: Identifier
    experiment_id: Identifier
    account: PaperAccountIdentity
    terms: DeploymentTerms
    idempotency_key: Identifier


class DeploymentAction(Contract):
    actor: Identifier
    reason: Text
    expected_revision: int = Field(ge=1)


class DeploymentApproval(DeploymentAction):
    review_id: Identifier
    expected_hash: Digest


class CapitalRevision(DeploymentAction):
    terms: DeploymentTerms


class DeploymentReviewDecision(DeploymentApproval):
    decision: Literal["reject","revise","defer"]


class DeploymentEvaluationInput(DeploymentAction):
    snapshot_id: Identifier
    as_of: AwareDatetime


class DeploymentTargetInput(DeploymentAction):
    evaluation_id: Identifier
    instrument_id: Identifier
    limit_price_usd: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


class DeploymentGate(Contract):
    name: str
    passed: bool
    detail: str


class FundingCapacity(Contract):
    account_equity_usd: Decimal
    other_envelopes_usd: Decimal
    unallocated_holdings_usd: Decimal
    unallocated_pending_buys_usd: Decimal
    own_holdings_usd: Decimal
    own_pending_buys_usd: Decimal
    proposed_envelope_usd: Decimal
    available_envelope_usd: Decimal
    allowed: bool
    limitations: list[str]
