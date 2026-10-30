"""Validated research inputs. Quantities and rates carry explicit units.

Only these declarative rules can be frozen; research payloads cannot contain
executable code, credentials, broker authority, or a desired lifecycle state.
"""
from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_serializer, model_validator


Identifier = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=160)]
Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=12000)]
Fraction = Annotated[Decimal, Field(ge=0, le=1, allow_inf_nan=False)]
PositiveMoney = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]
Money = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=6, allow_inf_nan=False)]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_default=True, str_strip_whitespace=True)


def canonical_json(value: BaseModel | dict | list) -> str:
    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def content_hash(value: BaseModel | dict | list) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class StrategyDraft(Contract):
    name: Annotated[str, StringConstraints(min_length=1, max_length=180)]
    hypothesis: Text
    rationale: Text


class Instrument(Contract):
    instrument_id: Identifier
    symbol: Identifier
    risk_group: Identifier
    currency: Literal["USD"] = "USD"


class RiskPolicy(Contract):
    max_position_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    max_group_fraction: Annotated[Decimal, Field(gt=0, le=1)]
    cash_reserve_fraction: Fraction
    max_turnover_fraction: Annotated[Decimal, Field(gt=0, le=2)]
    max_drawdown_fraction: Annotated[Decimal, Field(gt=0, lt=1)]

    @model_validator(mode="after")
    def check(self):
        if self.max_position_fraction > self.max_group_fraction:
            raise ValueError("position cap cannot exceed group cap")
        if self.cash_reserve_fraction >= 1:
            raise ValueError("cash reserve must leave investable capital")
        return self


class TrendRules(Contract):
    kind: Literal["diversified_trend"]
    lookbacks_sessions: list[Annotated[int, Field(ge=2, le=756)]] = Field(default=[63, 126, 252], min_length=1, max_length=5)
    volatility_sessions: Annotated[int, Field(ge=2, le=252)] = 63
    volatility_floor_fraction: Annotated[Decimal, Field(gt=0, le=1)] = Decimal("0.01")
    rebalance: Literal["weekly"] = "weekly"
    execution: Literal["next_session_open"] = "next_session_open"
    decision_latency_seconds: Annotated[int, Field(ge=0, le=3600)] = 1

    @model_validator(mode="after")
    def check(self):
        if self.lookbacks_sessions != sorted(set(self.lookbacks_sessions)):
            raise ValueError("lookbacks must be unique and increasing")
        return self


class GuidanceRules(Contract):
    kind: Literal["guidance_cash_quality"]
    arm: Literal["guidance_control", "numeric_quality", "astra_challenger"]
    hold_sessions: Annotated[int, Field(ge=1, le=252)] = 30
    execution: Literal["next_session_open"] = "next_session_open"
    excluded_groups: list[Identifier] = Field(default=["financials", "real_estate"], min_length=2)
    unknown_evidence: Literal["abstain"] = "abstain"
    decision_latency_seconds: Annotated[int, Field(ge=0, le=3600)] = 1
    entry_validity_sessions: Annotated[int, Field(ge=1, le=30)] = 5
    liquidity_sessions: Annotated[int, Field(ge=2, le=252)] = 20
    min_price_usd: PositiveMoney = Decimal("5")
    min_average_dollar_volume_usd: PositiveMoney = Decimal("1000000")
    max_financial_age_days: Annotated[int, Field(ge=30, le=366)] = 180
    financial_reporting_basis: Identifier = "GAAP"

    @model_validator(mode="after")
    def check(self):
        if not {"financials", "real_estate"}.issubset(self.excluded_groups):
            raise ValueError("initial cash-quality rules exclude financials and real estate")
        return self


class ModelRevision(Contract):
    provider_id: Identifier
    model_id: Identifier
    prompt_hash: Digest
    schema_version: Literal["guidance_evidence_v1"] = "guidance_evidence_v1"
    schema_hash: Digest
    historical_latency_seconds: Annotated[int, Field(ge=1, le=86400)] = 60
    provider_config_hash: Digest | None = None


class StrategySpec(Contract):
    schema_version: Literal[1] = 1
    universe: list[Instrument] = Field(min_length=1, max_length=500)
    rules: Annotated[TrendRules | GuidanceRules, Field(discriminator="kind")]
    risk: RiskPolicy
    feature_revision: Literal["research_features_v1"] = "research_features_v1"
    model: ModelRevision | None = None
    missing_input: Literal["no_signal"] = "no_signal"
    currency: Literal["USD"] = "USD"

    @model_validator(mode="after")
    def check(self):
        ids = [i.instrument_id for i in self.universe]
        symbols = [i.symbol.upper() for i in self.universe]
        if len(set(ids)) != len(ids) or len(set(symbols)) != len(symbols):
            raise ValueError("universe instruments and symbols must be unique")
        needs_model = isinstance(self.rules, GuidanceRules) and self.rules.arm == "astra_challenger"
        if needs_model != (self.model is not None):
            raise ValueError("only Astra challenger requires a pinned model revision")
        if isinstance(self.rules, GuidanceRules) and any(i.risk_group.casefold().replace(" ", "_") in self.rules.excluded_groups for i in self.universe):
            raise ValueError("guidance universe contains an excluded financial reporting group")
        return self


class FreezeVersion(Contract):
    spec: StrategySpec
    parent_version_id: Identifier | None = None
    design_id: Identifier | None = None


class TemporalSplit(Contract):
    train_start: date
    train_end: date
    validation_start: date
    validation_end: date
    holdout_start: date
    holdout_end: date
    embargo_sessions: Annotated[int, Field(ge=0, le=252)] = 0

    @model_validator(mode="after")
    def check(self):
        if not (self.train_start < self.train_end < self.validation_start < self.validation_end < self.holdout_start < self.holdout_end):
            raise ValueError("temporal splits must be disjoint and chronological")
        if self.holdout_end >= datetime.now(timezone.utc).date():
            raise ValueError("historical evaluation must end before today")
        return self


class CostScenario(Contract):
    name: Identifier
    slippage_bps: Annotated[Decimal, Field(ge=0, le=1000)]
    commission_usd: Money
    commission_bps: Annotated[Decimal, Field(ge=0, le=1000, allow_inf_nan=False)] = Decimal(0)
    execution_delay_sessions: Annotated[int, Field(ge=0, le=10)] = 0

    @model_serializer(mode="wrap")
    def retain_flat_fee_identity(self, handler):
        value = handler(self)
        # Existing frozen scenarios retain their canonical payload/hash.
        if self.commission_bps == 0:
            value.pop("commission_bps", None)
        return value

    def fee_for_fill(self, quantity: int, price: Decimal) -> Decimal:
        return self.commission_usd + abs(quantity) * price * self.commission_bps / Decimal(10000)


class AcceptanceCriteria(Contract):
    min_observations: Annotated[int, Field(ge=2, le=100000)]
    min_net_excess_return_fraction: Annotated[Decimal, Field(ge=-1, le=10)]
    max_drawdown_fraction: Annotated[Decimal, Field(gt=0, lt=1)]
    require_positive_stressed_excess: bool = True
    min_guidance_event_clusters: Annotated[int, Field(ge=2, le=100000)] = 30
    min_human_labels: Annotated[int, Field(ge=2, le=100000)] = 50
    min_classifier_accuracy_lower_bound: Fraction = Decimal(".8")
    rationale: Text


class ExtractionPolicy(Contract):
    """Operator-frozen metering assumptions; absence disables new model calls."""
    max_calls: Annotated[int, Field(ge=1, le=1000)]
    max_input_tokens: Annotated[int, Field(ge=1024, le=200000)] = 32768
    max_output_tokens: Annotated[int, Field(ge=128, le=8192)] = 2048
    input_usd_per_million: Money
    output_usd_per_million: Money
    pricing_reference: Text
    timeout_seconds: Annotated[int, Field(ge=1, le=300)] = 60
    availability_mode: Literal["historical", "observed"] = "historical"
    billing_mode: Literal["api_metered", "codex_subscription"] = "api_metered"

    @model_validator(mode="after")
    def subscription_pricing(self):
        if self.billing_mode == "codex_subscription" and (self.input_usd_per_million != 0 or self.output_usd_per_million != 0):
            raise ValueError("Codex subscription usage cannot be priced as an API token charge")
        return self

    @property
    def maximum_call_cost_usd(self) -> Decimal:
        from decimal import ROUND_UP
        return ((self.input_usd_per_million*self.max_input_tokens + self.output_usd_per_million*self.max_output_tokens)/Decimal(1000000)).quantize(Decimal(".000001"), rounding=ROUND_UP)


class EquityReference(Contract):
    instrument: Instrument
    initial_allocation_fraction: Annotated[Decimal, Field(gt=0, lt=1)]
    rationale: Text
    method: Literal["buy_and_hold"] = "buy_and_hold"


class ResearchPlanInput(Contract):
    strategy_id: Identifier
    family_id: Identifier
    version_ids: list[Identifier] = Field(min_length=1, max_length=12)
    split: TemporalSplit
    initial_capital_usd: PositiveMoney
    cash_annual_yield_fraction: Annotated[Decimal, Field(ge=0, le=1)] = Decimal("0")
    max_trials: Annotated[int, Field(ge=1, le=1000)]
    compute_budget_usd: PositiveMoney
    max_runtime_seconds: Annotated[int, Field(ge=1, le=86400)] = 300
    scenarios: list[CostScenario] = Field(min_length=3, max_length=10)
    criteria: AcceptanceCriteria
    extraction: ExtractionPolicy | None = None
    equity_reference: EquityReference | None = None

    @model_validator(mode="after")
    def check(self):
        if len(set(self.version_ids)) != len(self.version_ids):
            raise ValueError("version IDs must be unique")
        by_name = {s.name: s for s in self.scenarios}
        if len(by_name) != len(self.scenarios) or not {"base", "double_cost", "delayed"}.issubset(by_name):
            raise ValueError("unique base, double_cost and delayed scenarios are required")
        base, double, delayed = (by_name[n] for n in ("base", "double_cost", "delayed"))
        if double.slippage_bps < 2 * base.slippage_bps or double.commission_usd < 2 * base.commission_usd or double.commission_bps < 2 * base.commission_bps:
            raise ValueError("double_cost must charge at least twice base execution costs")
        if delayed.execution_delay_sessions <= base.execution_delay_sessions or delayed.slippage_bps < base.slippage_bps or delayed.commission_usd < base.commission_usd or delayed.commission_bps < base.commission_bps:
            raise ValueError("delayed scenario must delay execution without reducing costs")
        if self.extraction and self.extraction.maximum_call_cost_usd * self.extraction.max_calls > self.compute_budget_usd:
            raise ValueError("frozen maximum extraction charges exceed the research family budget")
        return self


class SnapshotManifest(Contract):
    provider: Identifier
    evidence_kind: Literal["fixture", "historical", "prospective"]
    provenance: Text
    entitlement: Text
    calendar: Identifier
    timezone: Identifier
    coverage_start: date
    coverage_end: date
    instrument_ids: list[Identifier] = Field(min_length=1, max_length=500)
    artifacts: dict[Identifier, Digest] = Field(min_length=1, max_length=20)
    availability: Literal["verified_publication", "recorded_receipt", "unverified", "synthetic"]
    limitations: list[Text] = Field(default_factory=list, max_length=50)
    normalization: Literal["raw_prices_explicit_actions"] = "raw_prices_explicit_actions"

    @model_validator(mode="after")
    def check(self):
        if self.coverage_end < self.coverage_start:
            raise ValueError("snapshot coverage is reversed")
        if len(set(self.instrument_ids)) != len(self.instrument_ids):
            raise ValueError("snapshot instruments must be unique")
        if self.evidence_kind == "fixture" and self.availability != "synthetic":
            raise ValueError("fixture availability must be labelled synthetic")
        if self.evidence_kind != "fixture" and self.availability == "synthetic":
            raise ValueError("synthetic data must be labelled fixture")
        if self.availability == "unverified" and not self.limitations:
            raise ValueError("unverified availability requires a coverage limitation")
        if self.evidence_kind == "prospective" and self.availability != "recorded_receipt":
            raise ValueError("prospective evidence requires recorded receipt")
        return self


class ExperimentInput(Contract):
    plan_id: Identifier
    snapshot_id: Identifier
    idempotency_key: Identifier
    evaluation: Literal["development", "validation", "holdout"] = "development"
    engine: Literal["lean", "local_replay"] = "local_replay"
    parent_experiment_id: Identifier | None = None


class ExperimentResult(Contract):
    schema_version: Literal[1] = 1
    engine_build: Identifier
    manifest_hash: Digest
    artifacts: dict[Identifier, Digest]
    evidence_status: Literal["fixture_only", "insufficient_evidence", "rejected", "eligible_for_paper_review"]
    explanation: Text
    # Values are validated by the engine-specific report contract before storage.
    report: dict
    operating_cost_usd: Money
