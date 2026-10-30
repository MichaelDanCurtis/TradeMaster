"""Native calendar/action capture and explicit normalization for research.

Capture completeness, source semantics and dataset admission remain separate.
No provider observation is labelled available at an earlier ex/process date.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from datetime import date, datetime, time as day_time, timezone
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import requests
from pydantic import AwareDatetime, Field, model_validator

from tradingagents.research.contracts import Contract, Digest, Text
from tradingagents.research.data.alpaca_capture import (
    CaptureError, CaptureLimits, CapturedPage, Symbol, _capture_pages, _object,
)
from tradingagents.research.data.contracts import CorporateAction, SecurityMapping, TradingSession
from tradingagents.research.data.store import ArtifactIntegrityError, ArtifactStore
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore

CALENDAR_ENDPOINT = "https://paper-api.alpaca.markets/v2/calendar"
ACTIONS_ENDPOINT = "https://data.alpaca.markets/v1/corporate-actions"
EXCHANGE_ZONE = ZoneInfo("America/New_York")


class ReferenceRequest(Contract):
    kind: Literal["calendar", "corporate_actions"]
    start: date
    end: date
    symbols: list[Symbol] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def check(self):
        if self.end < self.start or (self.end - self.start).days > 3660:
            raise ValueError("reference capture requires an ordered interval of at most ten years")
        if self.kind == "calendar":
            if self.symbols:
                raise ValueError("the US trading calendar does not take symbols")
            if self.start < date(1970, 1, 1) or self.end > date(2029, 12, 31):
                raise ValueError("calendar request exceeds the documented 1970-2029 coverage")
        elif not self.symbols or len(set(self.symbols)) != len(self.symbols):
            raise ValueError("corporate-action capture requires unique explicit symbols")
        self.symbols = sorted(self.symbols)
        return self

    @property
    def endpoint(self):
        return CALENDAR_ENDPOINT if self.kind == "calendar" else ACTIONS_ENDPOINT

    def params(self):
        result = {"start": self.start.isoformat(), "end": self.end.isoformat()}
        if self.kind == "calendar":
            return {**result, "date_type": "TRADING"}
        # Do not filter to supported types or hide early incomplete events.
        return {**result, "symbols": ",".join(self.symbols), "region": "us", "data_quality": "all",
                "sort": "asc", "limit": 1000}


class ReferenceCapture(Contract):
    schema_version: Literal["alpaca_reference_capture_v1"] = "alpaca_reference_capture_v1"
    request: ReferenceRequest
    endpoint: Literal[CALENDAR_ENDPOINT, ACTIONS_ENDPOINT]
    request_parameters: dict[str, str | int]
    limits: CaptureLimits
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: Literal["complete", "failed"]
    failure_code: str | None = Field(default=None, max_length=80)
    pages: list[CapturedPage] = Field(default_factory=list, max_length=100)
    received_rows: int = Field(ge=0)
    unique_rows: int = Field(ge=0)
    snapshot_ready: Literal[False] = False
    entitlement_status: Literal["not_verified"] = "not_verified"

    @model_validator(mode="after")
    def check(self):
        if self.endpoint != self.request.endpoint or self.request_parameters != self.request.params():
            raise ValueError("reference endpoint/parameters differ from the pinned protocol")
        if self.completed_at < self.started_at or (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("reference capture status/times are inconsistent")
        previous = self.started_at
        for index, page in enumerate(self.pages):
            if page.page_index != index or not previous <= page.requested_at <= page.processed_at <= self.completed_at:
                raise ValueError("reference receipt sequence is inconsistent")
            previous = page.processed_at
        return self


def _date(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise CaptureError("invalid_reference_date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CaptureError("invalid_reference_date") from exc


def calendar_session(row):
    if not isinstance(row, dict) or not {"date", "open", "close"} <= set(row):
        raise CaptureError("missing_calendar_fields")
    day = _date(row["date"])
    times = []
    for name in ("open", "close"):
        value = row[name]
        if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise CaptureError("invalid_calendar_time")
        instant = datetime.combine(day, day_time.fromisoformat(value), EXCHANGE_ZONE)
        # A native calendar should never specify an ambiguous/nonexistent wall time.
        if instant.utcoffset() != instant.replace(fold=1).utcoffset() or instant.astimezone(timezone.utc).astimezone(EXCHANGE_ZONE) != instant:
            raise CaptureError("ambiguous_calendar_time")
        times.append(instant)
    try:
        return TradingSession(date=day, opens_at=times[0], closes_at=times[1])
    except ValueError as exc:
        raise CaptureError("invalid_calendar_session") from exc


def _decode_reference(raw, request, seen, previous):
    try:
        payload = json.loads(raw, parse_float=Decimal, object_pairs_hook=_object)
    except (ValueError, UnicodeError) as exc:
        raise CaptureError("invalid_reference_json") from exc
    additions = {}
    rows = 0
    if request.kind == "calendar":
        if not isinstance(payload, list):
            raise CaptureError("invalid_calendar_response")
        for row in payload:
            session = calendar_session(row)
            day = session.date
            if not request.start <= day <= request.end:
                raise CaptureError("calendar_outside_request")
            if previous is not None and day < previous:
                raise CaptureError("unordered_calendar")
            original = additions.get(day.isoformat(), seen.get(day.isoformat()))
            if original is not None and original != row:
                raise CaptureError("conflicting_calendar_revision")
            additions[day.isoformat()] = row
            previous = day
            rows += 1
        return None, additions, rows, previous
    if not isinstance(payload, dict) or not {"corporate_actions", "next_page_token"} <= set(payload):
        raise CaptureError("missing_action_page_fields")
    token = payload["next_page_token"]
    if token is not None and (not isinstance(token, str) or not token or len(token) > 4096):
        raise CaptureError("invalid_page_token")
    groups = payload["corporate_actions"]
    if not isinstance(groups, dict):
        raise CaptureError("invalid_action_groups")
    for category, records in groups.items():
        if not category or len(category) > 100 or not isinstance(records, list):
            raise CaptureError("invalid_action_group")
        for row in records:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not 1 <= len(row["id"]) <= 120:
                raise CaptureError("missing_action_identity")
            if row.get("process_date") is not None:
                processed = _date(row["process_date"])
                if not request.start <= processed <= request.end:
                    raise CaptureError("action_process_date_outside_request")
            # Do not discard incomplete or unknown action types. Normalization
            # reports them as unresolved rather than pretending they do not exist.
            entry = {"category": category, "record": row}
            original = additions.get(row["id"], seen.get(row["id"]))
            if original is not None and original != entry:
                raise CaptureError("conflicting_action_revision")
            additions[row["id"]] = entry
            rows += 1
    return token, additions, rows, previous


def capture_reference(request: ReferenceRequest, store: ArtifactStore, *, secret_store, secret_ref,
                      http_client=None, clock=None, monotonic=None, limits=None):
    clock = clock or (lambda: datetime.now(timezone.utc))
    limits = limits or CaptureLimits()
    result, _ = _capture_pages(endpoint=request.endpoint, request_parameters=request.params(),
        decode_page=lambda raw, seen, previous: _decode_reference(raw, request, seen, previous),
        store=store, secret_store=secret_store, secret_ref=secret_ref,
        http_client=http_client or requests, clock=clock, monotonic=monotonic or time.monotonic,
        limits=limits, started=clock())
    return store.put_json(ReferenceCapture(request=request, endpoint=request.endpoint,
        request_parameters=request.params(), limits=limits, **result))


def read_reference_capture(store, digest):
    try:
        receipt = ReferenceCapture.model_validate(store.json(digest))
        _reference_records(store, receipt)
        return receipt
    except (ValueError, FileNotFoundError) as exc:
        raise ArtifactIntegrityError("Reference capture failed receipt/page verification") from exc


def _reference_records(store, receipt):
    seen, origins, tokens = {}, {}, set()
    token, previous = None, None
    count, total_bytes = 0, 0
    rejected = False
    for index, page in enumerate(receipt.pages):
        if rejected or page.request_page_token != token or (index and token is None):
            raise CaptureError("invalid_saved_page_chain")
        raw = store.get(page.response_artifact)
        total_bytes += len(raw)
        if len(raw) != page.response_bytes or len(raw) > receipt.limits.max_page_bytes or total_bytes > receipt.limits.max_bytes:
            raise CaptureError("invalid_saved_byte_count")
        if not page.accepted:
            rejected = True
            continue
        next_token, additions, rows, previous = _decode_reference(raw, receipt.request, seen, previous)
        if next_token is not None and next_token in tokens:
            raise CaptureError("invalid_saved_page_chain")
        if next_token is not None:
            tokens.add(next_token)
        token = next_token
        for key in additions:
            origins.setdefault(key, page)
        seen.update(additions)
        count += rows
    if len(receipt.pages) > receipt.limits.max_pages or count > receipt.limits.max_rows:
        raise CaptureError("invalid_saved_limits")
    if count != receipt.received_rows or len(seen) != receipt.unique_rows:
        raise CaptureError("invalid_saved_totals")
    if receipt.status == "complete" and (not receipt.pages or rejected or token is not None):
        raise CaptureError("unfinished_saved_capture")
    return seen, origins


class ActionNormalizationPolicy(Contract):
    """An operator's explicit interpretation; never verified provider metadata."""
    actor: Text
    rationale: Text
    cash_currency: Literal["USD"]
    payment_timing: Literal["end_of_payable_date_new_york"]


def normalize_references(store, calendar_hash: str, actions_hash: str, *, mappings: list[SecurityMapping],
                         policy: ActionNormalizationPolicy | None = None):
    """Return receipt-linked sessions/actions and every unresolved source row.

    This is an offline review artifact. It cannot certify coverage or register a
    snapshot. Mapping facts and optional cash interpretation remain user-declared.
    """
    calendar = read_reference_capture(store, calendar_hash)
    actions = read_reference_capture(store, actions_hash)
    if calendar.request.kind != "calendar" or actions.request.kind != "corporate_actions":
        raise ValueError("Normalization needs a calendar capture and an action capture")
    if calendar.status != "complete" or actions.status != "complete":
        raise ValueError("Partial provider captures cannot be normalized")
    calendar_rows, calendar_origins = _reference_records(store, calendar)
    action_rows, action_origins = _reference_records(store, actions)
    sessions = [calendar_session(row) for _, row in sorted(calendar_rows.items())]
    by_day = {session.date: session for session in sessions}
    normalized, issues, lineage = [], [], []
    if not sessions:
        issues.append({"source_id": None, "category": "calendar", "reasons": ["no_trading_sessions"]})
    for identifier, entry in action_rows.items():
        row, category = entry["record"], entry["category"]
        origin = action_origins[identifier]
        reasons = []
        action = None
        try:
            if category not in {"forward_splits", "reverse_splits", "cash_dividends"}:
                raise CaptureError("unsupported_action_type")
            common = {"id", "symbol", "process_date", "ex_date", "record_date", "payable_date"}
            if category == "cash_dividends":
                allowed = common | {"cusip", "rate", "special", "foreign", "currency", "due_bill_on_date", "due_bill_off_date"}
            else:
                allowed = common | {"cusip", "old_cusip", "new_cusip", "new_rate", "old_rate", "due_bill_redemption_date"}
            if set(row) - allowed:
                raise CaptureError("unsupported_action_fields")
            if not row.get("process_date"):
                raise CaptureError("missing_process_date")
            effective = _date(row.get("ex_date"))
            if effective not in by_day:
                raise CaptureError("effective_session_missing")
            if row.get("symbol") not in actions.request.symbols:
                raise CaptureError("unexpected_action_symbol")
            matches = [m for m in mappings if m.symbol == row.get("symbol") and
                       m.valid_from <= effective <= (m.valid_to or date.max) and m.known_at <= origin.processed_at]
            if len(matches) != 1:
                raise CaptureError("missing_or_ambiguous_instrument_mapping")
            if any(row.get(key) is not None for key in (
                    "due_bill_on_date", "due_bill_off_date", "due_bill_redemption_date")):
                raise CaptureError("due_bill_treatment_requires_review")
            base = {"action_id": f"alpaca:{identifier}", "instrument_id": matches[0].instrument_id,
                    "effective_session": effective, "available_at": origin.processed_at}
            if category in {"forward_splits", "reverse_splits"}:
                rates = []
                for name in ("new_rate", "old_rate"):
                    value = row.get(name)
                    if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or not Decimal(value).is_finite() or value <= 0:
                        raise CaptureError("invalid_split_ratio")
                    rates.append(Decimal(value))
                with localcontext() as context:
                    context.prec = 36
                    ratio = rates[0] / rates[1]
                if (category == "forward_splits" and ratio <= 1) or (category == "reverse_splits" and ratio >= 1):
                    raise CaptureError("split_direction_mismatch")
                action = CorporateAction(**base, kind="split", split_ratio=ratio)
            else:
                if row.get("foreign") is not False or row.get("special") is not False:
                    raise CaptureError("nonordinary_or_unclassified_cash_dividend")
                if policy is None:
                    raise CaptureError("cash_currency_and_payment_policy_required")
                value = row.get("rate")
                if isinstance(value, bool) or not isinstance(value, (int, Decimal)) or not Decimal(value).is_finite() or value < 0:
                    raise CaptureError("invalid_dividend_rate")
                if row.get("currency") not in {None, "USD"}:
                    raise CaptureError("dividend_currency_mismatch")
                payable = _date(row.get("payable_date"))
                if payable < effective:
                    raise CaptureError("payment_precedes_entitlement")
                payment = datetime.combine(payable, day_time(23, 59, 59, 999999), EXCHANGE_ZONE)
                action = CorporateAction(**base, kind="dividend", cash_per_share_usd=Decimal(value), payable_at=payment)
        except (ValueError, ArithmeticError) as exc:
            reasons.append(str(exc) if isinstance(exc, CaptureError) else "unsupported_normalized_value")
        if action is not None and not reasons:
            normalized.append(action.model_dump(mode="json"))
        else:
            issues.append({"source_id": identifier, "category": category, "reasons": reasons})
        lineage.append({"source_id": identifier, "category": category, "response_artifact": origin.response_artifact,
                        "received_at": origin.received_at.isoformat(), "available_at": origin.processed_at.isoformat(),
                        "process_date": row.get("process_date"),
                        "ex_date": row.get("ex_date") if isinstance(row.get("ex_date"), str) else None})
    report = {"schema_version": "alpaca_reference_normalization_v1", "calendar_capture": calendar_hash,
        "actions_capture": actions_hash, "snapshot_ready": False, "entitlement_status": "not_verified",
        "sessions": [session.model_dump(mode="json") for session in sessions], "actions": normalized,
        "issues": issues, "action_lineage": lineage,
        "calendar_lineage": [{"session": day, "response_artifact": page.response_artifact,
            "available_at": page.processed_at.isoformat()} for day, page in sorted(calendar_origins.items())],
        "declared_mappings": [m.model_dump(mode="json") for m in mappings],
        "declared_cash_policy": policy.model_dump(mode="json") if policy else None,
        "limitations": ["Action request dates cover provider processing dates, not guaranteed ex-date coverage.",
            "Empty action results do not establish the absence of late or missing corporate actions.",
            "Source availability is actual receipt/processing; historical availability is not reconstructed.",
            "Calendar response completeness and instrument mappings need independent coverage review.",
            "Normalized rows are a review artifact; price-session semantics and snapshot admission remain separate."]}
    if policy:
        report["limitations"].append("USD cash units and end-of-payable-day timing are explicit operator assumptions, not observed broker payments.")
    return store.put_json(report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture")
    capture.add_argument("--request", type=Path, required=True)
    capture.add_argument("--secret-ref", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("receipt_hash")
    normalize = commands.add_parser("normalize")
    normalize.add_argument("--calendar", required=True)
    normalize.add_argument("--actions", required=True)
    normalize.add_argument("--mappings", type=Path, required=True)
    normalize.add_argument("--cash-policy", type=Path)
    args = parser.parse_args()
    store = ArtifactStore(args.artifacts)
    if args.command == "normalize":
        mappings = [SecurityMapping.model_validate(row) for row in json.loads(args.mappings.read_bytes())]
        policy = ActionNormalizationPolicy.model_validate_json(args.cash_policy.read_bytes()) if args.cash_policy else None
        digest = normalize_references(store, args.calendar, args.actions, mappings=mappings, policy=policy)
        report = store.json(digest)
        print(json.dumps({"normalization_hash": digest, "sessions": len(report["sessions"]),
            "actions": len(report["actions"]), "issues": report["issues"], "snapshot_ready": False}))
        return 2 if report["issues"] else 0
    if args.command == "capture":
        request = ReferenceRequest.model_validate_json(args.request.read_bytes())
        if args.secret_ref.startswith("env:"):
            secrets = EnvSecretStore()
        elif args.secret_ref.startswith("keychain:"):
            secrets = MacKeychainSecretStore()
        else:
            parser.error("Use an existing env: or keychain: secret reference")
        digest = capture_reference(request, store, secret_store=secrets, secret_ref=args.secret_ref)
    else:
        digest = args.receipt_hash
    receipt = read_reference_capture(store, digest)
    print(json.dumps({"receipt_hash": digest, "kind": receipt.request.kind, "status": receipt.status,
        "failure_code": receipt.failure_code, "pages": len(receipt.pages), "unique_rows": receipt.unique_rows,
        "snapshot_ready": False, "entitlement_status": "not_verified"}))
    return 0 if receipt.status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
