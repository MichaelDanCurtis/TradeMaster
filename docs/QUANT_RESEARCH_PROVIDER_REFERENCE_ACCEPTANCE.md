# Provider calendar and corporate-action acceptance

TradeMaster now captures Alpaca's US trading calendar and corporate actions as
immutable native responses, and produces an offline normalization review with
source lineage. The shared transport retains the existing daily-bar capture
behavior. No capture or normalization creates a research snapshot or trading job.

## Validated interpretation

The calendar reader uses the paper-domain `GET /v2/calendar` with explicit
`date_type=TRADING`, start and end dates. It preserves returned market days and
open/close times, including early closes; it does not generate weekdays or fill
holidays. Native `HH:MM` times become `America/New_York` instants with the applicable
daylight-saving offset. Ambiguous/nonexistent wall times, reversed sessions,
out-of-request days and conflicting revisions fail explicitly. Requests outside
the documented 1970–2029 interval are rejected rather than treating unsupported
coverage as an empty calendar.

Sources: [US calendar reference](https://docs.alpaca.markets/us/reference/legacycalendar),
[official SDK calendar parsing](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/trading/models.py),
and [Alpaca's calendar timezone clarification](https://forum.alpaca.markets/t/calendar-endpoint/11190).

The corporate-action reader uses `GET /v1/corporate-actions` with explicit symbols,
US region, `data_quality=all`, ascending sort and token pagination. It leaves the
type filter unset so unsupported and incomplete events remain visible. Request
dates describe **processing-date coverage**, not ex-date coverage. Native IDs,
original amounts/ratios and dates remain in the raw response artifact. Identical
duplicates retain the first receipt; conflicting same-ID revisions fail the
capture and retain the conflicting page for inspection.

The [corporate-actions reference](https://docs.alpaca.markets/us/reference/corporateactions-1)
documents the processing-date query and possible availability delays. The
[official SDK source models](https://github.com/alpacahq/alpaca-py/blob/master/alpaca/data/models/corporate_actions.py)
provide the native split/dividend field shapes used in local fixtures.

## Normalization review

`normalize_references` checks both complete captures and every native page again.
The resulting content-addressed report contains:

- Trading sessions and their calendar response/receipt lineage.
- Supported split/dividend rows linked to exact source artifacts, source IDs,
  processing dates, ex-dates and actual receipt/processing availability.
- Every unresolved action and a specific reason; no unknown action is dropped
  from the review because the current research engine cannot represent it.
- The operator-declared instrument mappings and optional cash interpretation.

Forward and reverse splits use `new_rate / old_rate` with decimal arithmetic and
direction checks. Ordinary domestic cash dividends require an explicit USD policy
and end-of-payable-date timing policy, plus an actor and rationale. The timing
policy is a conservative analytical assumption, **not an observed broker payment**.
Foreign/special/unclassified dividends, due-bill cases, unknown source fields,
missing payment dates, incompatible currency, unsupported action types, unavailable
or ambiguous mappings and missing effective sessions remain unresolved.

Source availability is the recorded processing time of the received page. The
adapter never backdates knowledge to a processing date, ex-date or payable date.
The report preserves the distinction between an action taking effect and the
system first learning about it.

Every report retains `snapshot_ready=false` and `entitlement_status=not_verified`.
Empty action responses cannot prove no corporate actions occurred. Missing
calendar coverage, permanent instrument identity, late events, native price
aggregation/session semantics, data-use rights and snapshot admission still need
separate validation. These are explicit limits on this intermediate artifact.

## Operator commands

Request examples use these shapes:

```json
{"kind":"calendar","start":"2026-09-01","end":"2026-09-10"}
```

```json
{"kind":"corporate_actions","symbols":["SPY"],"start":"2026-09-01","end":"2026-09-10"}
```

Run only with an existing credential reference and a chosen artifact directory:

```sh
.venv/bin/python -m tradingagents.research.data.alpaca_reference \
  --artifacts /absolute/path/to/research-artifacts capture \
  --request /absolute/path/to/request.json --secret-ref env:EXISTING_ALPACA_JSON_SECRET
```

Offline inspection and normalization:

```sh
.venv/bin/python -m tradingagents.research.data.alpaca_reference \
  --artifacts /absolute/path/to/research-artifacts inspect RECEIPT_SHA256
```

```sh
.venv/bin/python -m tradingagents.research.data.alpaca_reference \
  --artifacts /absolute/path/to/research-artifacts normalize \
  --calendar CALENDAR_RECEIPT_SHA256 --actions ACTION_RECEIPT_SHA256 \
  --mappings /absolute/path/to/mappings.json --cash-policy /absolute/path/to/cash-policy.json
```

Mappings use the existing `SecurityMapping` schema. The optional cash-policy file
uses `actor`, `rationale`, `cash_currency: "USD"`, and
`payment_timing: "end_of_payable_date_new_york"`. Omitting it still permits split
normalization and leaves dividend interpretation unresolved. Commands return exit
code two for a failed capture or unresolved normalization; zero does not confer
snapshot eligibility.

The transport retains the daily-bar capture's fixed endpoint allowlist, redirect
refusal, byte/page/row/socket bounds and cooperative elapsed budget. A supervising
process is still needed for a whole-cycle deadline before unattended scheduling.

## Evidence

The reference suite covers early close and DST conversion, missing/invalid calendar
rows, native pagination, incomplete/unsupported events, processing-date versus
ex-date queries, source conflicts, mapping/currency/payment issues, receipt
tampering, offline CLI/restart behavior and empty-coverage handling.

A hand-calculated integration fixture sends the normalized split and dividend into
the existing trend engine: raw prices of 100, 51 and 50.75, a 2-for-1 split and a
1.25 dividend produce the same total-return signal, volatility and covariance risk
as the unadjusted 100, 102 and 104 sequence. A cutoff before the recorded receipt
produces no signal. This establishes software accounting behavior, not investment
performance.

Loopback HTTP acceptance uses the actual `requests` streaming transport for both
reference endpoints. It verifies GET-only traffic, explicit query parameters and
a retained 403 failure without retry or alternate source. All credentials and
provider responses are synthetic fixtures. No real provider call, account access,
data subscription or order occurred; no frontend code changed.

Final focused verification on 2026-09-05: **94 passed** in 1.96 seconds across
reference capture, daily-bar capture, dataset/contracts, trend and the existing
chart-provider suites. Log: `/tmp/trademaster-reference-final.log`. Compilation and
tracked diff checks also passed. The full implementation plan remains active.
