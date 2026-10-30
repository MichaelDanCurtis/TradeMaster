# Research explorer

Open Research → Research explorer. This is a read-only discovery surface backed
by the configured Alpaca market-data provider. Opening it or pressing Refresh
reads up to 25 gainers, 25 decliners, and 25 most-active securities by share volume.
It does not submit orders or make model calls.

The browse order interleaves the source rankings, merges repeated symbols, and
retains each reason a symbol appeared. Research paths, ticker search, price
thresholds, missing-price inclusion, and watchlist membership filter that sample
locally. Unknown prices are explicitly optional and do not pass a strict price
screen. Non-finite numeric inputs become unavailable values.

Provider update timestamps and retrieval timestamps are separate. Each source
can fail independently; a failed source is labeled unavailable and its exception
text is not exposed. Refresh failures retain the previous successful read with
its original timestamps. The explorer has no background polling schedule.

Watch adds to the existing browser-persisted watchlist. Research opens the chosen
symbol in the existing committee workspace; the user can inspect saved reports
or request a new review with the configured research provider.

## Boundaries

This is a screener sample, not whole-market fundamental coverage or an investment
recommendation. Lists can contain funds, warrants, rights, and leveraged products;
security type and eligibility are not yet enriched. Most-active data may supply
volume without a price. High share volume is not a relative-volume anomaly or
proof of institutional buying. A price decline does not establish undervaluation.
The explorer's questions are deterministic research prompts, not AI findings.

Further work: security/company enrichment, issuer relevance ranking, and primary
filings. The brief workflow below now provides evidence-linked synthesis.

## Evidence research briefs

Choose **Brief** on a candidate or enter a ticker in the Evidence research brief
panel, then press **Write brief**. This uses the configured research-designer
provider through the existing Codex App Server adapter and ChatGPT sign-in.
This initial integration accepts Codex subscription providers only; it does not
fall back to a metered AI API or the older quick-scan provider.

Each explicit request captures one usable bid/ask quote and up to five linked,
dated Finnhub company-news headlines/summaries from the last seven days. News
coverage may include indirectly related companies. Source retrieval timestamps
are distinct from event/publication times. Invalid quotes, including zero asks,
and missing news become retained evidence gaps. No usable sources means no model
call. Company fundamentals and primary filings are not yet collected.

A single isolated Codex turn returns an overview, sourced catalysts, bull and bear
arguments, rejection questions, and gaps. The response must match the schema and
the selected model identity. Every claim must reference an existing source and an
exact excerpt; accepted quotations are limited per source. Inferences are labeled
AI interpretations. These checks establish traceability, not semantic correctness
or investment value. Thin evidence can legitimately yield empty thesis sections.

The source packet, its fingerprint, model receipt and usage are stored in
`ui_explorer_briefs`. The panel shows the latest ten attempts and their preserved
source links/excerpts. A request identifier prevents duplicate dispatch after a
lost response; only one brief may be active at a time. Collection and synthesis
states reflect actual work. Failed or interrupted attempts are retained and never
automatically retried. Expired attempts become unknown and cannot accept a late
result. Each model call has a 90-second timeout inside a killable child process;
the overall request deadline is 180 seconds. Observed subscription usage is not a
guaranteed hard token cap and is not priced as an API dollar charge.

The brief worker gets public source text and its Codex binding, with no broker
credentials. The existing adapter disables tools, integrations and trading
authority for the model turn. No order or strategy execution is triggered.

## Verification

- Four backend tests: evidence normalization/merging, partial failures, malformed
  versus empty responses, and read-only API integration.
- Three filter tests included in the 163 passing frontend tests; production build
  passed.
- Local browser: actual source read returned 71 distinct symbols with September 4
  provider update times; tested search, strict missing-price exclusion, declines,
  watchlist save and reload persistence, and the GPRO symbol-research handoff.
  Removed the temporary GPRO watchlist entry afterward.
- Research, deployment, and execution-scheduler workers reported healthy
  heartbeats after the local service restart.
- Brief tests cover exact citations, model identity/tool rejection, malformed
  output, quote limits, news date/link validation, missing-source behavior,
  concurrent idempotency, one active request, expiry, provider changes and saved
  child receipts, uncertain outcomes and API request recovery. Brief/explorer
  suite: 15 passed. Existing API regression suite: 69 passed. Frontend: 163 passed.
- Actual Codex App Server calls on September 6, 2026 confirmed `gpt-6-astra`:
  `brief_02ccf20dd69d4d0188f566751532a51d` (NVDA) passed citation validation and
  declined to invent a thesis from indirectly related coverage. The unusable
  zero-ask quote was excluded. `brief_eb002b16cd7845c0834329c6b8b6b65d` (PLTR)
  passed with one catalyst, one bull argument and two bear arguments. These are
  workflow checks, not validation of an investment strategy.
