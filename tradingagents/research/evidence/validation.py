from __future__ import annotations

from datetime import datetime

from tradingagents.research.contracts import ModelRevision
from tradingagents.research.data.contracts import DatasetBundle, EvidenceObservation, GuidanceClassification, GuidanceNotice
from tradingagents.research.strategies.guidance_quality import notice_range


def validate_classification(classification: GuidanceClassification, dataset: DatasetBundle, notice: GuidanceNotice,
                            *, as_of: datetime, document_ids: set[str]) -> list[str]:
    """The model never validates its own figures, citations or comparable period."""
    errors = []
    if classification.notice_id != notice.notice_id:
        errors.append("Classifier returned a different notice")
    if (classification.period_start, classification.period_end, classification.reporting_basis) != (notice.period_start, notice.period_end, notice.reporting_basis):
        errors.append("Classifier period/reporting basis differs from the original observations")
    expected_range = notice_range(dataset, notice)
    if expected_range is None or (classification.guidance_low_usd, classification.guidance_high_usd) != expected_range:
        errors.append("Extracted USD guidance does not match independent source numbers")
    docs = {d.document_id: d for d in dataset.documents}
    if not classification.passages:
        errors.append("Classification has no source passage")
    cited_current_notice = False
    for passage in classification.passages:
        doc = docs.get(passage.document_id)
        if doc is None or passage.document_id not in document_ids:
            errors.append("Citation is not in the exact model input")
            continue
        if doc.availability.available_at > as_of:
            errors.append("Citation was unavailable at the model input cutoff")
        if passage.end <= passage.start or passage.end > len(doc.text) or doc.text[passage.start:passage.end] != passage.quote:
            errors.append("Citation offsets/text do not match the immutable source")
        cited_current_notice |= passage.document_id == notice.document_id
    if not cited_current_notice:
        errors.append("Classification must cite the current guidance source")
    return list(dict.fromkeys(errors))


def evidence_verdict(record: EvidenceObservation, dataset: DatasetBundle, notice: GuidanceNotice,
                     model: ModelRevision, as_of: datetime) -> tuple[str, list[str]]:
    from tradingagents.research.evidence.extraction import extraction_input, input_hash, prompt_hash, schema_hash
    errors = list(record.validation_errors)
    if record.notice_id != notice.notice_id or record.model != model:
        errors.append("Evidence is not from the pinned notice/model revision")
    if record.actual_provider_id != model.provider_id or record.actual_model_id != model.model_id:
        errors.append("Actual model/provider identity was not confirmed against the pin")
    if model.prompt_hash != prompt_hash() or model.schema_hash != schema_hash():
        errors.append("Pinned prompt/schema is unsupported by this validator build")
    if record.availability.available_at > as_of or record.input_as_of > as_of:
        errors.append("Model evidence is not yet available")
    packet = extraction_input(dataset, notice, record.input_as_of)
    if record.input_hash != input_hash(packet):
        errors.append("Evidence input hash does not match the source snapshot")
    latest_packet = extraction_input(dataset, notice, as_of)
    if packet["documents"] != latest_packet["documents"]:
        errors.append("New source information requires a fresh classification")
    if record.classification is None:
        errors.append("No valid structured classification")
    else:
        try:
            if GuidanceClassification.model_validate_json(record.raw_output) != record.classification:
                errors.append("Validated classification differs from the preserved model response")
        except ValueError:
            errors.append("Preserved model response is not valid structured evidence")
        errors.extend(validate_classification(record.classification, dataset, notice, as_of=record.input_as_of,
            document_ids={d["document_id"] for d in packet["documents"]}))
    if errors:
        return "unknown", list(dict.fromkeys(errors))
    return record.classification.verdict, []
