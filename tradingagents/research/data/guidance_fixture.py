"""Labelled synthetic guidance events. No real issuer, market return or model call."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import hashlib

from tradingagents.research.contracts import ModelRevision, SnapshotManifest, StrategySpec, canonical_json
from tradingagents.research.data.contracts import (
    Availability, DatasetBundle, EvidencePassage, FinancialObservation,
    GuidanceClassification, GuidanceNotice, HumanEvidenceLabel, SecurityMapping, SourceDocument,
)
from tradingagents.research.data.fixtures import trend_fixture
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.evidence.extraction import Completion, extract, prompt_hash, schema_hash


def fixture_model() -> ModelRevision:
    return ModelRevision(provider_id="synthetic-fixture", model_id="labelled-fixture-classifier-v1", prompt_hash=prompt_hash(), schema_hash=schema_hash())


def fixture_guidance_spec(arm: str) -> StrategySpec:
    return StrategySpec.model_validate({
        "universe": [{"instrument_id": f"sim-{name}", "symbol": f"SIM-{name.upper()}", "risk_group": "industrials"} for name in ("clean", "oneoff", "weak", "unknown")],
        "rules": {"kind": "guidance_cash_quality", "arm": arm},
        "risk": {"max_position_fraction": ".2", "max_group_fraction": ".8", "cash_reserve_fraction": ".1", "max_turnover_fraction": "1", "max_drawdown_fraction": ".2"},
        "model": fixture_model().model_dump(mode="json") if arm == "astra_challenger" else None,
    })


def synthetic_availability(at: datetime, revision: str) -> Availability:
    return Availability(mode="synthetic", event_time=at, published_at=at, ingested_at=at, processed_at=at, available_at=at, revision=revision)


def guidance_fixture() -> DatasetBundle:
    prices = trend_fixture()
    docs, facts, notices, labels, evidence, bars, mappings = [], [], [], [], [], [], []
    names = ("clean", "oneoff", "weak", "unknown")

    def document(identifier, text, at):
        doc = SourceDocument(document_id=identifier, text=text, text_hash=hashlib.sha256(text.encode()).hexdigest(),
            source_url=f"fixture://{identifier}", availability=synthetic_availability(at, identifier))
        docs.append(doc)
        return doc

    for number, name in enumerate(names):
        instrument = f"sim-{name}"
        mappings.append(SecurityMapping(instrument_id=instrument, symbol=f"SIM-{name.upper()}", valid_from=prices.sessions[0].date, known_at=prices.sessions[0].opens_at))
        for bar in prices.bars:
            if bar.instrument_id == "us-sim-eq":
                values = bar.model_dump()
                values.update(instrument_id=instrument, volume=100000)
                for field in ("open", "high", "low", "close"):
                    values[field] = (values[field] * (Decimal(1) + Decimal(number) / 10)).quantize(Decimal(".000001"))
                bars.append(type(bar)(**values))
        for year in (2018, 2019):
            for quarter, (month, day) in enumerate(((3, 31), (6, 30), (9, 30), (12, 31)), start=1):
                end = date(year, month, day)
                at = datetime.combine(end + timedelta(days=30), datetime.min.time(), timezone.utc).replace(hour=22)
                revenue_quarter = Decimal(100 if year == 2018 else 110)
                cash_quarter = Decimal(10 if year == 2018 else -5 if name == "weak" else 20)
                doc = document(f"{name}-{year}-q{quarter}", f"Synthetic GAAP report for {instrument}, cumulative from {year}-01-01 through {end}. Revenue USD {revenue_quarter*quarter} million; operating cash flow USD {cash_quarter*quarter} million.", at)
                for metric, value in (("revenue", revenue_quarter*quarter), ("operating_cash_flow", cash_quarter*quarter)):
                    facts.append(FinancialObservation(observation_id=f"{doc.document_id}-{metric}", instrument_id=instrument, metric=metric,
                        period_start=date(year, 1, 1), period_end=end, period_type="annual" if quarter == 4 else "year_to_date",
                        value=value, original_value=str(value), unit="USD_millions", reporting_basis="GAAP", document_id=doc.document_id, availability=doc.availability))
        explanation = {
            "clean": "Management attributes the increase to recurring customer demand, explicitly excludes one-time items, confirms unchanged reporting basis, and reconciles comparative guidance without unresolved contradictions.",
            "oneoff": "The increase depends entirely on a one-time litigation recovery. The GAAP reporting basis is unchanged and the reconciliation contains no unresolved contradiction.",
            "weak": "Management attributes the increase to recurring demand, excludes one-time items, confirms unchanged reporting basis, and reconciles comparative guidance without unresolved contradictions.",
            "unknown": "Management declined to explain the drivers, basis comparability or inconsistencies.",
        }[name]
        for event_name, day, low, high in (("prior", 3, 900, 1100), ("raise", 10, 1100, 1300), ("repeat", 17, 1200, 1400)):
            at = datetime(2020, 2, day, 22, tzinfo=timezone.utc)
            identifier = f"{name}-{event_name}"
            doc = document(identifier, f"For fiscal year 2020 (2020-01-01 to 2020-12-31), on the GAAP basis, revenue guidance is USD {low} million to USD {high} million. {explanation}", at)
            for metric, value in (("revenue_guidance_low", low), ("revenue_guidance_high", high)):
                facts.append(FinancialObservation(observation_id=f"{identifier}-{metric}", instrument_id=instrument, metric=metric,
                    period_start=date(2020, 1, 1), period_end=date(2020, 12, 31), period_type="forecast", value=value, original_value=str(value),
                    unit="USD_millions", reporting_basis="GAAP", document_id=identifier, availability=doc.availability))
            notices.append(GuidanceNotice(notice_id=identifier, instrument_id=instrument, document_id=identifier, period_start=date(2020, 1, 1),
                period_end=date(2020, 12, 31), reporting_basis="GAAP", state="range", low_observation_id=f"{identifier}-revenue_guidance_low", high_observation_id=f"{identifier}-revenue_guidance_high", availability=doc.availability))
            if event_name != "prior":
                verdict = "exclude" if name == "oneoff" else "unknown" if name == "unknown" else "clean"
                labels.append(HumanEvidenceLabel(notice_id=identifier, annotator="fixture-authors", labelled_at=datetime(2026, 9, 4, tzinfo=timezone.utc), expected_verdict=verdict, rationale="Hand-authored classification of explicitly synthetic source text"))
        at = datetime(2020, 3, 2, 22, tzinfo=timezone.utc)
        doc = document(f"{name}-withdrawal", "The issuer withdraws its revenue guidance for fiscal year 2020 on the GAAP basis.", at)
        notices.append(GuidanceNotice(notice_id=doc.document_id, instrument_id=instrument, document_id=doc.document_id, period_start=date(2020, 1, 1),
            period_end=date(2020, 12, 31), reporting_basis="GAAP", state="withdrawn", availability=doc.availability))
    dataset = DatasetBundle(timezone=prices.timezone, sessions=prices.sessions, bars=bars, mappings=mappings, documents=docs, financials=facts, guidance_notices=notices, human_labels=labels)
    by_doc = {d.document_id: d for d in docs}
    for notice in notices:
        if notice.state != "range" or notice.notice_id.endswith("-prior"):
            continue
        name = notice.instrument_id.removeprefix("sim-")
        current = [o for o in facts if o.observation_id in {notice.low_observation_id, notice.high_observation_id}]
        values = {o.metric: o.value_usd for o in current}
        doc = by_doc[notice.document_id]
        classification = GuidanceClassification(notice_id=notice.notice_id, period_start=notice.period_start, period_end=notice.period_end,
            reporting_basis="GAAP", currency="USD", guidance_low_usd=values["revenue_guidance_low"], guidance_high_usd=values["revenue_guidance_high"],
            one_time_dependency="yes" if name == "oneoff" else "unknown" if name == "unknown" else "no",
            reporting_basis_change="unknown" if name == "unknown" else "no", unresolved_contradiction="unknown" if name == "unknown" else "no",
            passages=[EvidencePassage(document_id=doc.document_id, start=0, end=len(doc.text), quote=doc.text)])
        class FixtureClient:
            def complete(self, **kwargs):
                return Completion(text=canonical_json(classification), provider_id=fixture_model().provider_id, model_id=fixture_model().model_id, input_tokens=0, output_tokens=0, cost_usd=Decimal(0))
        times = iter((notice.availability.available_at, notice.availability.available_at + timedelta(seconds=60)))
        evidence.append(extract(dataset=dataset, notice=notice, model=fixture_model(), input_as_of=notice.availability.available_at,
            client=FixtureClient(), reserved_cost_usd=Decimal(0), mode="synthetic", clock=lambda: next(times)))
    return DatasetBundle.model_validate({**dataset.model_dump(mode="json"), "evidence": [e.model_dump(mode="json") for e in evidence]})


def save_guidance_fixture(store: ArtifactStore) -> SnapshotManifest:
    data = guidance_fixture()
    return SnapshotManifest(provider="synthetic-guidance-fixture-v1", evidence_kind="fixture", provenance="Hand-authored issuer events, labels and synthetic prices; fixture classifier outputs are not Astra observations",
        entitlement="Repository-generated engineering fixture", calendar="synthetic_weekdays", timezone=data.timezone,
        coverage_start=data.sessions[0].date, coverage_end=data.sessions[-1].date, instrument_ids=sorted(m.instrument_id for m in data.mappings),
        artifacts=store.put_dataset(data), availability="synthetic", limitations=["Artificial, selected events and synthetic weekday prices; includes market holidays", "Hand-authored model outputs test validation and arm mechanics only; no actual model was invoked"])
