# Opportunity inbox and historical replay

Open **Research → Opportunity inbox**.

## Company discovery

Choose the editable 32-company starting basket, the watchlist, or 1–40 explicit
symbols. Set revenue-growth and net-margin thresholds and whether positive annual
free cash flow is required. **Scan and save evidence** queues one explicit scan.
The API reads one company at a time using the existing research desk's Finnhub and
SEC collector. No new AI API connection is required.

Each result retains its immutable company snapshot, previous snapshot identity,
source timestamps/hashes/links, financial checks, security classification, and gaps.
Priority is the count of research reasons, not a return forecast or probability:

- Passing all selected financial thresholds.
- A higher revenue-growth or margin estimate than the prior capture.
- A higher reported annual free-cash-flow value, with both period ends shown.
- Previously unseen filings dated within the last 30 days. First-capture filings
  are identified explicitly; their significance has not been assessed.

Missing facts do not pass. Current provider estimates may lack underlying as-of
dates, and financial changes may reflect new periods or restatements. The basket
is an editable sample, not exhaustive market coverage or a historical universe.
Common-stock status is verified only where the existing collector finds an exact
symbol on a filing cover. An unverified instrument remains flagged.

Progress is based on processed companies, with individual failed collections
retained separately. Stop preserves the current read and skips the remaining
companies. An API restart marks unfinished scans interrupted and never retries
them automatically. One API process is supported. Scanning is read-only at the
providers and has no trading or model-dispatch interface.

Dispositions and notes are append-only desk records. The latest disposition for a
symbol is shown across scans. "Watch" is an inbox label; it does not create a
background thesis monitor. Company evidence opens the selected issuer in Research
desk; Open Astra brief opens the existing explicit brief workflow. No model runs
merely because a scan completes or a candidate is opened.

## Historical decision rehearsal

Start a replay from a candidate or from the replay section. Select an exchange
session, SIP or IEX, and 1–60 completed future sessions to reveal. The existing
Forecast Lab capture adapter preserves raw Alpaca responses and normalizes daily
split-adjusted closing prices and volume. Sixty historical context sessions and
every target bar are required; missing bars are not interpolated.

The browser initially receives only the context ending on the decision date.
Write a research decision, reasoning, and a specific invalidation condition.
**Save decision and reveal next session** records a content-addressed decision
receipt before advancing one session. Duplicate/stale cursor submissions are
rejected. There is no automatic mutation retry. Reopening uses the original
capture and journal, not refreshed prices.

This first replay room is a price-based decision rehearsal. It intentionally
excludes today's company metrics, briefs, and forecasts from the historical view.
It does not yet reconstruct historical filings or invoke Astra against historical
evidence. Today's price revisions/split adjustments, symbol selection and human
hindsight remain possible. The visible close change excludes dividends, trading
rules, fees and execution costs. It is not a strategy return or a blind holdout.

## Storage and verification

Records use the existing `ui_research_desk` table with kinds `opportunity_scan`,
`opportunity_triage`, and `decision_replay`. Replay captures and decision receipts
are stored under `.research-artifacts/opportunities/objects`, keyed by SHA-256.
The replay API never returns the unfiltered internal payload or future bars.

Focused tests in `tests/ui/test_opportunity_lab.py` cover incremental progress,
failures, cancellation during reads, interrupted-scan recovery, missing facts,
filing recency, append-only dispositions, hidden outcomes, duplicate decisions,
missing sessions, artifact corruption, durable replay reopening, and route wiring.

Verified on September 6, 2026: 42 focused backend tests and all 163 frontend tests
passed, as did a cold TypeScript check and production build (two pre-existing
unused-variable warnings remain in unrelated components). Browser verification
ran a real NVDA/MSFT/XOM scan with 23 source receipts; results included pass, fail,
and unknown checks. A real NVDA SIP replay from June 1, 2023 saved two explicitly
labeled workflow-verification decisions, revealed June 2 and June 5, and reopened
with both receipts intact. Company navigation, persisted disposition filtering,
and correct-symbol Astra brief selection were exercised. No model call was
started. The paper-trial plan hash was unchanged and execution attempts remained
zero. Evidence: `.research-artifacts/opportunities/browser-verification.json`.
