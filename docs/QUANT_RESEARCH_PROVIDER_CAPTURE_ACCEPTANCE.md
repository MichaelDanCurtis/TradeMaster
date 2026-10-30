# Alpaca raw daily-bar capture acceptance

The research path can now capture an explicitly selected Alpaca feed across all
response pages, save the original JSON bytes and request/receipt/processing times,
and revalidate the receipt after restart. It does not register a dataset, select
a strategy, queue an evaluation, or place an order. The existing chart adapter is
unchanged.

## Scope and source semantics

The capture uses `GET https://data.alpaca.markets/v2/stocks/bars` with explicit
`timeframe=1Day`, `adjustment=raw`, `currency=USD`, `sort=asc`, `asof=-`, and an
operator-selected `iex` or `sip` feed. Disabling automatic symbol remapping keeps
the requested ticker identity explicit; a separate instrument-mapping review is
still required. The request interval and exact parameters are saved in the receipt.

The [official historical bars reference](https://docs.alpaca.markets/us/reference/stockbars)
documents sorting by symbol then timestamp, page limits across symbols, and the
need to follow `next_page_token` even when a response contains fewer rows than its
limit. The adapter follows that token until an explicit terminal response. It
records absent symbols, accepts identical boundary duplicates once in the unique
count, and fails on conflicting revisions or out-of-order data.

The [official corporate-actions reference](https://docs.alpaca.markets/us/reference/corporateactions-1)
does not guarantee immediate creation/availability after announcement. This
capture therefore makes no corporate-action completeness or historical
publication-time claim. A daily bar's native timestamp remains untouched; it is
not substituted for receipt time or treated as proof that a completed session's
bar was available then.

`status=complete` means the requested page sequence finished and passed the native
bar checks. Every receipt still has `snapshot_ready=false` and
`entitlement_status=not_verified`. A successful request establishes neither
exchange-wide coverage nor contractual permission to retain/use the data. The
capture contains no normalized trading calendar, corporate-action chain, permanent
instrument IDs, guidance documents, or historical availability reconstruction.
Those are required before producing an eligible research/prospective snapshot.

## Explicit operator entry point

Create a JSON request with uppercase symbols, an explicit feed and timezone-aware
start/end timestamps. The end must not be in the future. For example, this is a
request format illustration, not a command executed during acceptance:

```json
{
  "symbols": ["SPY"],
  "start": "2026-09-01T00:00:00Z",
  "end": "2026-09-04T23:59:59Z",
  "feed": "sip"
}
```

Use an existing JSON credential secret through the project's existing `env:` or
`keychain:` secret store. Credentials are not command-line arguments or artifacts.

```sh
.venv/bin/python -m tradingagents.research.data.alpaca_capture \
  --artifacts /absolute/path/to/research-artifacts \
  capture --request /absolute/path/to/request.json \
  --secret-ref env:EXISTING_ALPACA_JSON_SECRET
```

The command prints the receipt hash and a concise capture summary. Completed
captures exit zero; retained failed attempts exit two. Reinspect without network
access:

```sh
.venv/bin/python -m tradingagents.research.data.alpaca_capture \
  --artifacts /absolute/path/to/research-artifacts inspect RECEIPT_SHA256
```

Defaults cap capture at 100 pages, 500,000 received rows, 4 MB per response, 32 MB
total, a 15-second maximum socket timeout and a cooperative 60-second elapsed
budget. The elapsed budget is checked between requests, stream chunks and page
validation; it is **not a whole-process deadline** against a stalled credential
store or a trickling response. Unattended scheduling still requires process
supervision. No redirect, retry, feed fallback or subscription purchase occurs.

Complete HTTP 200 bodies are preserved even when semantic validation rejects the
page. Earlier valid pages survive later transport/provider failures. Truncated or
oversize bodies and non-200 bodies are not retained. Error summaries omit provider
exception text and response bodies so credentials cannot leak through those paths.

## Local verification

`tests/research/test_alpaca_capture.py` exercises native-shaped fixtures for:

- Multi-symbol pagination, empty intermediate pages, missing symbols and exact raw
  JSON preservation, including decimal precision beyond displayed chart values.
- Duplicate observations, conflicting revisions, timestamp/price/volume failures,
  unexpected symbols, repeated tokens and cross-page ordering.
- Page, row, byte and elapsed limits; denial/rate-limit/server responses; retained
  partial attempts and sanitized transport failures.
- Artifact tampering, request-parameter substitution, page-chain/receipt-total
  integrity and native-body verification after a fresh process starts.
- Actual loopback HTTP streaming and pagination through `requests`, with GET-only
  traffic and proof that redirect targets are never requested.
- The executable CLI's missing-credential failure and offline inspection paths.

These tests use local fixture credentials and loopback responses only. They do
not establish real Alpaca access, data-use rights, feed completeness, a genuine
reference dataset, scheduled observation, research eligibility or broker-paper
readiness. No frontend behavior changed in this slice.

Final validation on 2026-09-05: **54 passed** across the capture, data, contract and
existing chart-provider suites in 1.07 seconds. Log:
`/tmp/trademaster-alpaca-capture-tests-final.log`. Python compilation, tracked diff
checks and explicit whitespace checks of the four touched files also passed.

Run the capture and adjacent data/contract/chart-provider regressions with:

```sh
.venv/bin/python -m pytest tests/research/test_alpaca_capture.py \
  tests/research/test_data.py tests/research/test_contracts.py \
  tests/ui/test_market_data.py -q
```
