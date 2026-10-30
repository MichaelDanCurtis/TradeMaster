from datetime import timedelta
from decimal import Decimal as D
import json

import pytest

from tradingagents.research.data.guidance_fixture import guidance_fixture, fixture_model
from tradingagents.research.evidence.extraction import Completion, extract, extraction_input
from tradingagents.research.evidence.validation import evidence_verdict


@pytest.fixture
def dataset():
    return guidance_fixture()


def pair(dataset, name="clean"):
    return (next(n for n in dataset.guidance_notices if n.notice_id == f"{name}-raise"),
        next(e for e in dataset.evidence if e.notice_id == f"{name}-raise"))


def test_validated_verdicts_and_processing_latency(dataset):
    for name, verdict in (("clean", "clean"), ("oneoff", "exclude"), ("unknown", "unknown")):
        notice, evidence = pair(dataset, name)
        assert evidence_verdict(evidence, dataset, notice, fixture_model(), evidence.availability.available_at) == (verdict, [])
        assert evidence_verdict(evidence, dataset, notice, fixture_model(), notice.availability.available_at)[0] == "unknown"


@pytest.mark.parametrize("corruption", ["number", "period", "quote", "offset", "provider", "model", "raw"])
def test_corrupt_or_unconfirmed_output_abstains(dataset, corruption):
    notice, evidence = pair(dataset)
    if corruption == "number": evidence.classification.guidance_low_usd = D(1)
    if corruption == "period": evidence.classification.period_end += timedelta(days=365)
    if corruption == "quote": evidence.classification.passages[0].quote = "invented"
    if corruption == "offset": evidence.classification.passages[0].start = 1
    if corruption == "provider": evidence.actual_provider_id = "other-provider"
    if corruption == "model": evidence.actual_model_id = "other-model"
    if corruption == "raw": evidence.raw_output = "{}"
    verdict, errors = evidence_verdict(evidence, dataset, notice, fixture_model(), evidence.availability.available_at)
    assert verdict == "unknown" and errors


def test_tools_and_order_fields_are_rejected_without_a_favorable_default(dataset):
    notice, original = pair(dataset)
    class Client:
        def complete(self, **kwargs):
            assert "untrusted source data" in kwargs["system"]
            assert kwargs["schema"]["additionalProperties"] is False
            return Completion(text=json.dumps({"approve_order": True}), provider_id=fixture_model().provider_id,
                model_id=fixture_model().model_id, tool_calls=True)
    clock = iter((original.call_started_at, original.call_completed_at))
    evidence = extract(dataset=dataset, notice=notice, model=fixture_model(), input_as_of=notice.availability.available_at,
        client=Client(), reserved_cost_usd=D(".25"), mode="historical", clock=lambda: next(clock))
    assert evidence.classification is None and evidence.cost_usd == D(".25")
    assert any("forbidden tool" in error for error in evidence.validation_errors)


def test_input_contains_no_future_documents_or_human_labels(dataset):
    notice, evidence = pair(dataset)
    packet = extraction_input(dataset, notice, notice.availability.available_at)
    assert "clean-repeat" not in [doc["document_id"] for doc in packet["documents"]]
    assert "expected_verdict" not in json.dumps(packet)
    dataset.human_labels[0].rationale = "never give this to the model"
    assert packet == extraction_input(dataset, notice, notice.availability.available_at)


def test_unavailable_call_is_charged_once_and_never_retried(dataset):
    notice, original = pair(dataset)
    class Client:
        calls = 0
        def complete(self, **kwargs):
            self.calls += 1
            raise TimeoutError("unknown response")
    client = Client()
    clock = iter((original.call_started_at, original.call_completed_at))
    evidence = extract(dataset=dataset, notice=notice, model=fixture_model(), input_as_of=notice.availability.available_at,
        client=client, reserved_cost_usd=D(".25"), mode="historical", clock=lambda: next(clock))
    assert client.calls == 1 and evidence.cost_usd == D(".25")
    assert evidence.classification is None and evidence.actual_model_id == "unconfirmed"
    assert "contamination" in evidence.availability.latency_assumption


def test_observed_evidence_waits_for_real_completion_and_preserves_response_bytes(dataset):
    notice, original = pair(dataset)
    text = "\n" + original.raw_output + "\n"
    class Client:
        def complete(self, **kwargs):
            return Completion(text=text, provider_id=fixture_model().provider_id, model_id=fixture_model().model_id, cost_usd=D(".02"))
    finish = original.call_started_at + timedelta(seconds=80)
    clock = iter((original.call_started_at, finish))
    evidence = extract(dataset=dataset, notice=notice, model=fixture_model(), input_as_of=notice.availability.available_at,
        client=Client(), reserved_cost_usd=D(".25"), mode="observed", clock=lambda: next(clock))
    assert evidence.availability.available_at == finish
    assert evidence.raw_output == text and evidence.cost_usd == D(".02")


def test_exact_source_and_passage_whitespace_are_preserved(dataset):
    import hashlib
    from tradingagents.research.data.contracts import EvidencePassage, SourceDocument
    document = dataset.documents[0]
    text = "\n  " + document.text + "\n"
    copy = SourceDocument.model_validate({**document.model_dump(), "text": text, "text_hash": hashlib.sha256(text.encode()).hexdigest()})
    passage = EvidencePassage(document_id=copy.document_id, start=0, end=len(text), quote=text)
    assert copy.text == passage.quote == text


def test_invalid_cost_metadata_preserves_and_identifies_the_reservation(dataset):
    notice, original = pair(dataset)
    class Client:
        def complete(self, **kwargs):
            return Completion(text=original.raw_output, provider_id=fixture_model().provider_id, model_id=fixture_model().model_id, cost_usd=D("NaN"))
    clock = iter((original.call_started_at, original.call_completed_at))
    evidence = extract(dataset=dataset, notice=notice, model=fixture_model(), input_as_of=notice.availability.available_at,
        client=Client(), reserved_cost_usd=D(".25"), mode="historical", clock=lambda: next(clock))
    assert evidence.cost_usd == D(".25") and evidence.cost_basis == "configured_upper_bound"
    assert any("invalid cost" in error for error in evidence.validation_errors)
