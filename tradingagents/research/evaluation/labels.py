"""Human-labelled classification quality, independent of portfolio returns."""
from __future__ import annotations

from datetime import date
from math import sqrt
from pydantic import Field

from tradingagents.research.contracts import Contract, ModelRevision
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.evidence.validation import evidence_verdict


class LabelEvaluation(Contract):
    labels: int
    completed: int
    invalid: int
    correct: int
    accuracy: float | None
    accuracy_lower_bound: float | None
    confusion: dict[str, dict[str, int]]
    evidence_ids: list[str] = Field(default_factory=list)
    method: str = "First dispatched attempt per labelled notice, including failures; absent output counts as missing. Wilson 95% interval assumes independent labels and is not investment evidence."


def evaluate_labels(dataset: DatasetBundle, model: ModelRevision, start: date, end: date) -> LabelEvaluation:
    notices = {n.notice_id: n for n in dataset.guidance_notices}
    labels = [label for label in dataset.human_labels if start <= notices[label.notice_id].availability.available_at.date() <= end]
    confusion = {expected: dict.fromkeys(("clean", "exclude", "unknown", "invalid", "missing"), 0) for expected in ("clean", "exclude", "unknown")}
    ids, correct, invalid, completed = [], 0, 0, 0
    for label in labels:
        candidates = sorted((e for e in dataset.evidence if e.notice_id == label.notice_id and e.model == model
            and e.availability.available_at.date() <= end), key=lambda e: (e.call_started_at, e.evidence_id))
        actual = "missing"
        if candidates:
            first = candidates[0]
            ids.append(first.evidence_id)
            completed += 1
            actual, errors = evidence_verdict(first, dataset, notices[label.notice_id], model, first.availability.available_at)
            if errors:
                actual, invalid = "invalid", invalid+1
        confusion[label.expected_verdict][actual] += 1
        correct += actual == label.expected_verdict
    count = len(labels)
    fraction = correct / count if count else None
    z = 1.959963984540054
    lower = (fraction + z*z/(2*count) - z*sqrt(fraction*(1-fraction)/count + z*z/(4*count*count)))/(1+z*z/count) if count else None
    return LabelEvaluation(labels=count, completed=completed, invalid=invalid, correct=correct, accuracy=fraction,
        accuracy_lower_bound=lower, confusion=confusion, evidence_ids=ids)
