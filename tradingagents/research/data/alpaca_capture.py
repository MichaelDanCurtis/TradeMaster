"""Explicit, read-only capture of Alpaca daily bars; never a research snapshot.

Native pages and receipt times survive restart. Pagination completeness proves
only that this request finished, not exchange coverage, licensing, historical
availability, corporate-action completeness, or permission to trade.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Literal

import requests
from pydantic import AwareDatetime, ConfigDict, Field, StringConstraints, model_validator

from tradingagents.research.contracts import Contract, Digest
from tradingagents.research.data.store import ArtifactIntegrityError, ArtifactStore
from tradingagents.ui.market_data.alpaca import _parse_credentials
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore

ENDPOINT = "https://data.alpaca.markets/v2/stocks/bars"
Symbol = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9.\-]{0,14}$")]


class DailyBarRequest(Contract):
    symbols: list[Symbol] = Field(min_length=1, max_length=50)
    start: AwareDatetime
    end: AwareDatetime
    feed: Literal["iex", "sip"]

    @model_validator(mode="after")
    def check(self):
        if self.start >= self.end or (self.end - self.start).days > 3660:
            raise ValueError("capture needs an ordered interval no longer than ten years")
        if len(set(self.symbols)) != len(self.symbols):
            raise ValueError("capture symbols must be unique")
        self.symbols = sorted(self.symbols)
        return self

    def params(self):
        return {"symbols": ",".join(self.symbols), "start": self.start.astimezone(timezone.utc).isoformat(),
                "end": self.end.astimezone(timezone.utc).isoformat(), "feed": self.feed,
                "timeframe": "1Day", "adjustment": "raw", "asof": "-", "currency": "USD",
                "sort": "asc", "limit": 10000}


class CaptureLimits(Contract):
    max_pages: int = Field(default=100, ge=1, le=100)
    max_rows: int = Field(default=500000, ge=1, le=500000)
    max_bytes: int = Field(default=32000000, ge=1, le=32000000)
    max_page_bytes: int = Field(default=4000000, ge=1, le=4000000)
    elapsed_seconds: int = Field(default=60, ge=1, le=300)


class CapturedPage(Contract):
    # Pagination tokens are opaque native values, not operator-entered text.
    model_config = ConfigDict(str_strip_whitespace=False)
    page_index: int = Field(ge=0, lt=100)
    requested_at: AwareDatetime
    received_at: AwareDatetime
    processed_at: AwareDatetime
    request_page_token: str | None = Field(default=None, max_length=4096)
    response_artifact: Digest
    response_bytes: int = Field(ge=0, le=4000000)
    accepted: bool

    @model_validator(mode="after")
    def check(self):
        if not self.requested_at <= self.received_at <= self.processed_at:
            raise ValueError("capture processing must follow request and receipt")
        return self


class DailyBarCapture(Contract):
    schema_version: Literal["alpaca_daily_capture_v1"] = "alpaca_daily_capture_v1"
    endpoint: Literal[ENDPOINT] = ENDPOINT
    request: DailyBarRequest
    request_parameters: dict[str, str | int]
    limits: CaptureLimits
    started_at: AwareDatetime
    completed_at: AwareDatetime
    status: Literal["complete", "failed"]
    failure_code: str | None = Field(default=None, max_length=80)
    pages: list[CapturedPage] = Field(default_factory=list, max_length=100)
    received_rows: int = Field(ge=0)
    unique_rows: int = Field(ge=0)
    observed_symbols: list[Symbol]
    missing_symbols: list[Symbol]
    snapshot_ready: Literal[False] = False
    entitlement_status: Literal["not_verified"] = "not_verified"

    @model_validator(mode="after")
    def check(self):
        if self.request_parameters != self.request.params():
            raise ValueError("saved request parameters differ from the pinned capture protocol")
        if self.completed_at < self.started_at or self.request.end > self.started_at:
            raise ValueError("capture interval or receipt time is in the future")
        if (self.status == "failed") != (self.failure_code is not None):
            raise ValueError("only failed captures have a failure code")
        previous = self.started_at
        for index, page in enumerate(self.pages):
            if page.page_index != index or not previous <= page.requested_at <= page.processed_at <= self.completed_at:
                raise ValueError("capture page receipt sequence is inconsistent")
            previous = page.processed_at
        return self


class CaptureError(ValueError):
    """An intentionally non-sensitive error code, never a response body."""


def _timestamp(value):
    if not isinstance(value, str):
        raise CaptureError("invalid_bar_timestamp")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CaptureError("invalid_bar_timestamp") from exc
    if result.tzinfo is None:
        raise CaptureError("invalid_bar_timestamp")
    return result


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CaptureError("duplicate_json_key")
        result[key] = value
    return result


def _decode_page(raw, request, seen, previous_key):
    """Validate native data without rounding prices or inventing empty coverage."""
    try:
        payload = json.loads(raw, parse_float=Decimal, object_pairs_hook=_object)
    except (ValueError, UnicodeError) as exc:
        raise CaptureError("invalid_page_json") from exc
    if not isinstance(payload, dict) or "bars" not in payload or "next_page_token" not in payload:
        raise CaptureError("missing_page_fields")
    token = payload["next_page_token"]
    if token is not None and (not isinstance(token, str) or not token or len(token) > 4096):
        raise CaptureError("invalid_page_token")
    bars = payload["bars"]
    if bars is None:
        bars = {}
    if not isinstance(bars, dict) or set(bars) - set(request.symbols):
        raise CaptureError("unexpected_symbols")
    additions = {}
    rows = 0
    for symbol in sorted(bars):
        if not isinstance(bars[symbol], list):
            raise CaptureError("invalid_bar_list")
        for bar in bars[symbol]:
            if not isinstance(bar, dict) or not {"t", "o", "h", "l", "c", "v"} <= set(bar):
                raise CaptureError("missing_bar_fields")
            timestamp = _timestamp(bar["t"])
            if not request.start <= timestamp <= request.end:
                raise CaptureError("bar_outside_request")
            prices = []
            for name in ("o", "h", "l", "c"):
                value = bar[name]
                if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
                    raise CaptureError("invalid_bar_price")
                price = Decimal(value)
                if not price.is_finite() or price <= 0:
                    raise CaptureError("invalid_bar_price")
                prices.append(price)
            opening, high, low, close = prices
            if not low <= min(opening, close) <= max(opening, close) <= high:
                raise CaptureError("invalid_bar_ohlc")
            if isinstance(bar["v"], bool) or not isinstance(bar["v"], int) or bar["v"] < 0:
                raise CaptureError("invalid_bar_volume")
            key = (symbol, timestamp)
            original = additions.get(key, seen.get(key))
            if original is not None and original != bar:
                raise CaptureError("conflicting_bar_revision")
            if previous_key is not None and key < previous_key:
                raise CaptureError("unordered_bars")
            previous_key = key
            additions[key] = bar
            rows += 1
    return token, additions, rows, previous_key


def _capture_pages(*, endpoint, request_parameters, decode_page, store, secret_store, secret_ref,
                   http_client, clock, monotonic, limits, started):
    """Shared bounded native transport for bars, calendar and corporate actions."""
    if endpoint not in {ENDPOINT, "https://paper-api.alpaca.markets/v2/calendar",
                        "https://data.alpaca.markets/v1/corporate-actions"}:
        raise ValueError("Unsupported read-only capture endpoint")
    deadline = monotonic() + limits.elapsed_seconds
    pages, seen, tokens = [], {}, set()
    token, previous_key = None, None
    count, total_bytes = 0, 0
    failure = None

    def remaining():
        seconds = deadline - monotonic()
        if seconds <= 0:
            raise CaptureError("elapsed_limit")
        return min(15, seconds)

    try:
        try:
            credentials = _parse_credentials(secret_store.get_secret(secret_ref))
        except Exception as exc:
            raise CaptureError("credentials_unavailable") from exc
        headers = {"APCA-API-KEY-ID": credentials["key_id"], "APCA-API-SECRET-KEY": credentials["secret_key"]}
        while True:
            if len(pages) >= limits.max_pages:
                raise CaptureError("page_limit")
            params = dict(request_parameters)
            if token is not None:
                params["page_token"] = token
            requested_at = clock()
            # Never forward credentials to a redirect target or persist headers.
            response = http_client.get(endpoint, params=params, headers=headers,
                timeout=remaining(), stream=True, allow_redirects=False)
            try:
                if response.status_code != 200:
                    raise CaptureError(f"http_{int(response.status_code)}")
                chunks, size = [], 0
                for chunk in response.iter_content(chunk_size=8192):
                    remaining()
                    size += len(chunk)
                    if size > limits.max_page_bytes or total_bytes + size > limits.max_bytes:
                        raise CaptureError("response_byte_limit")
                    chunks.append(chunk)
                raw = b"".join(chunks)
                received_at = clock()
                remaining()
            finally:
                response.close()
            total_bytes += len(raw)
            digest = store.put(raw)
            accepted = False
            try:
                next_token, additions, rows, next_key = decode_page(raw, seen, previous_key)
                if count + rows > limits.max_rows:
                    raise CaptureError("row_limit")
                if next_token is not None and next_token in tokens:
                    raise CaptureError("repeated_page_token")
                remaining()
                accepted = True
            finally:
                pages.append(CapturedPage(page_index=len(pages), requested_at=requested_at,
                    received_at=received_at, processed_at=clock(), request_page_token=token,
                    response_artifact=digest, response_bytes=len(raw), accepted=accepted))
            seen.update(additions)
            count += rows
            previous_key = next_key
            if next_token is None:
                break
            tokens.add(next_token)
            token = next_token
    except CaptureError as exc:
        failure = str(exc)
    except Exception:
        # Provider/credential exceptions may include secrets or request headers.
        failure = "capture_unavailable"
    return {"started_at": started, "completed_at": clock(), "pages": pages,
            "status": "failed" if failure else "complete", "failure_code": failure,
            "received_rows": count, "unique_rows": len(seen)}, seen


def capture_daily_bars(request: DailyBarRequest, store: ArtifactStore, *, secret_store, secret_ref: str,
                       http_client=None, clock=None, monotonic=None, limits: CaptureLimits | None = None):
    """Return the immutable receipt digest, including a failed/partial attempt.

    This function has socket, byte, page and cooperative elapsed limits. A
    supervising process must impose a wall-clock deadline for unattended use.
    No retries, alternative feeds, redirects, data subscriptions or orders.
    """
    clock = clock or (lambda: datetime.now(timezone.utc))
    monotonic = monotonic or time.monotonic
    limits = limits or CaptureLimits()
    http_client = http_client or requests
    started = clock()
    if started.tzinfo is None or request.end > started:
        raise ValueError("capture end must be no later than the actual request time")
    result, seen = _capture_pages(endpoint=ENDPOINT, request_parameters=request.params(),
        decode_page=lambda raw, seen, previous: _decode_page(raw, request, seen, previous),
        store=store, secret_store=secret_store, secret_ref=secret_ref, http_client=http_client,
        clock=clock, monotonic=monotonic, limits=limits, started=started)
    symbols = sorted({key[0] for key in seen})
    receipt = DailyBarCapture(request=request, request_parameters=request.params(), limits=limits,
        **result, observed_symbols=symbols, missing_symbols=sorted(set(request.symbols) - set(symbols)))
    return store.put_json(receipt)


def read_capture(store: ArtifactStore, digest: str) -> DailyBarCapture:
    """Revalidate the saved native pages, pagination chain and receipt totals."""
    try:
        receipt = DailyBarCapture.model_validate(store.json(digest))
        seen, tokens = {}, set()
        token, previous_key = None, None
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
            next_token, additions, rows, previous_key = _decode_page(raw, receipt.request, seen, previous_key)
            if next_token is not None and next_token in tokens:
                raise CaptureError("invalid_saved_page_chain")
            if next_token is not None:
                tokens.add(next_token)
            token = next_token
            seen.update(additions)
            count += rows
        symbols = sorted({key[0] for key in seen})
        if len(receipt.pages) > receipt.limits.max_pages or count > receipt.limits.max_rows:
            raise CaptureError("invalid_saved_limits")
        if (count, len(seen), symbols, sorted(set(receipt.request.symbols) - set(symbols))) != (
                receipt.received_rows, receipt.unique_rows, receipt.observed_symbols, receipt.missing_symbols):
            raise CaptureError("invalid_saved_totals")
        if receipt.status == "complete" and (not receipt.pages or rejected or token is not None):
            raise CaptureError("unfinished_saved_capture")
        return receipt
    except (ValueError, FileNotFoundError) as exc:
        raise ArtifactIntegrityError("Daily bar capture failed receipt/page verification") from exc


def capture_summary(receipt: DailyBarCapture):
    return {"status": receipt.status, "failure_code": receipt.failure_code, "feed": receipt.request.feed,
            "pages": len(receipt.pages), "received_rows": receipt.received_rows, "unique_rows": receipt.unique_rows,
            "missing_symbols": receipt.missing_symbols, "started_at": receipt.started_at.isoformat(),
            "completed_at": receipt.completed_at.isoformat(), "snapshot_ready": False,
            "entitlement_status": "not_verified",
            "message": "Raw response capture only. Calendar, instrument mapping, corporate actions, historical availability and data-use rights need separate validation."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts", type=Path, required=True)
    commands = parser.add_subparsers(dest="command", required=True)
    capture = commands.add_parser("capture", help="Explicit provider read; no snapshot registration")
    capture.add_argument("--request", type=Path, required=True, help="DailyBarRequest JSON")
    capture.add_argument("--secret-ref", required=True, help="Existing env:NAME or keychain:service:account JSON credentials")
    inspect = commands.add_parser("inspect", help="Verify an existing capture without network access")
    inspect.add_argument("receipt_hash")
    args = parser.parse_args()
    store = ArtifactStore(args.artifacts)
    if args.command == "capture":
        request = DailyBarRequest.model_validate_json(args.request.read_bytes())
        if args.secret_ref.startswith("env:"):
            secrets = EnvSecretStore()
        elif args.secret_ref.startswith("keychain:"):
            secrets = MacKeychainSecretStore()
        else:
            parser.error("Use an existing env: or keychain: secret reference")
        digest = capture_daily_bars(request, store, secret_store=secrets, secret_ref=args.secret_ref)
    else:
        digest = args.receipt_hash
    receipt = read_capture(store, digest)
    print(json.dumps({"receipt_hash": digest, **capture_summary(receipt)}))
    return 0 if receipt.status == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
