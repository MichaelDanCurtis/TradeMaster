# Market Pulse

Market Pulse is the default desktop workspace: a dense trading workstation with an
on-demand, source-linked explanation of the top five gainers and five losers.
Open it from the primary navigation or with Cmd/Ctrl+5. Existing shortcuts 1–4
remain unchanged.

## Use the desk

1. Configure **Alpaca market data** in Settings, including the desired snapshot
   feed. The board retrieves seven benchmark/asset ETF proxies, eleven sector
   ETF proxies, the top gainers and losers, and the volume leaders.
2. Select a scanner row to update the persistent chart and research desk together.
   The scanner includes all 25 gainers and 25 losers, sortable columns, a company
   and symbol filter, and separate gainers, losers and most-active views. Arrow
   keys on a ticker button select adjacent rows. Research and Watchlist buttons
   use the existing workflows.
3. Configure the existing **Codex subscription research provider** in Settings
   and sign in to Codex with ChatGPT. For company news, set `news_provider` to
   `"alpaca"` in the Alpaca market-data provider configuration to reuse its account.
   The default remains Finnhub, which uses `FINNHUB_API_KEY` from your local
   environment. Neither source silently falls back to the other.
4. Choose **Explain top 10**. TradeMaster preserves that capture, gathers up to
   two dated news items per selected symbol, and asks the configured model for
   one combined assessment. Fewer symbols are analyzed if the provider returns
   fewer valid movers.
5. Inspect the catalyst, possible alternative explanations, and linked excerpts.
   A result distinguishes a reported event, a possible connection, and insufficient
   evidence. A reported event is not proof that the event caused the price move.

Market refresh runs every 60 seconds while the view is visible and auto-refresh
is enabled. Manual refresh uses a 10-second server cache floor. Neither starts AI.
A single global research brief can be active at a time; requests for the same
capture and provider configuration are deduplicated. Explanations survive reloads.
After prices refresh, earlier assessments are labeled as earlier captures and their
catalyst badges are not applied to the new ranking.

## Selected-stock workbench

Click a scanner row, benchmark or sector ETF to link the chart and detail desk.
On desktop, the default layout places the scanner above the research desk on the
left and a full-height chart on the right. Compact market and sector strips sit
above these panes. Each pane scrolls independently inside the viewport.

The selected security stays visible while switching between **Catalyst Desk**,
**Charts** (supplemental quote figures and a chart-focus shortcut), and
**Company & Figures**. The primary chart remains mounted beside every tab,
preserving its range and style. Company identity and ownership do not depend on
an AI explanation being available.

- **Identity:** exact-symbol names and security types from Alpaca's read-only
  paper asset directory, with company names beneath mover tickers.
- **Company & Figures:** a public Yahoo Finance profile, business description,
  financial figures, up to ten reported institutional positions and ten reported
  insider/beneficial-owner positions. Holdings include report dates; direct and
  indirect positions remain separate. These records may be old, incomplete or
  overlapping. A parent is displayed only when explicitly supplied by the source;
  otherwise it says the parent is not established. Fund sponsorship and management
  roles are not treated as proof of ownership or control. Warrant symbols are not
  silently replaced with common-share symbols.
- **Charts:** configured-feed Alpaca bars in 1D, 5D, 1M and 1Y ranges, with candle
  and line views, volume, zoom and pan. 1D uses the latest available trading
  session. Bars are unadjusted and may show stock-split jumps. Intraday axis labels
  use the browser's local time. Missing data stays unavailable.
- **Layout:** use the position menu or drag the Detail desk handle to dock left,
  right or below. Drag the outside edge to resize, or focus it and use arrow keys.
  Position, width and selected tab are saved in this browser. Reset restores the
  scanner-above-research layout. The workstation uses a new preference key so
  older dashboard layouts do not override the new default. Narrow screens stack
  the scanner, chart and research panels with bounded internal scrolling.

The read-only routes are `/api/market-pulse/identities`,
`/api/market-pulse/company/{symbol}` and `/api/market-pulse/chart/{symbol}`.
Successful lookups are cached for 24 hours, six hours and 60 seconds respectively;
failed lookups are cached for 60 seconds. Public company requests run in a child
process with a 25-second deadline and without broker credentials. Neither tab
switching nor selecting a stock starts an AI assessment.

## What the numbers mean

- **Movers and volume rankings:** Alpaca's SIP screener, independently of the
  snapshot feed. Prices and percent changes in the movers tables come from that
  ranking. Rankings reset at the market open; before the open they can describe
  the previous session. See [Alpaca movers](https://docs.alpaca.markets/us/reference/movers-1).
- **Supplemental data:** one explicitly configured-feed batch of up to 100
  symbols. IEX covers a single exchange; it is not consolidated market volume.
  Day volume, VWAP and quotes can differ from the SIP ranking. No silent switch
  to another feed occurs when access is denied. See
  [Alpaca snapshots](https://docs.alpaca.markets/us/reference/stocksnapshots-1).
- **Benchmarks and sectors:** ETF prices, not index levels or full-market breadth.
  The sector count is how many of the reporting sector ETFs are advancing.
- **Freshness:** source timestamps are separate from capture/retrieval timestamps.
  Missing or invalid values remain blank. Old snapshots can remain visible with
  their ages. Spreads older than 15 minutes, crossed quotes, and invalid prices
  are not presented as usable current metrics.
- **News:** linked, dated Alpaca or Finnhub headlines and summaries within the four
  days preceding the ranking timestamp are eligible. Later news is excluded.
  Alpaca articles must match the ticker and have no revision after the ranking
  timestamp. Each ticker fetch is capped at one 50-item page; company-specific
  reports are preferred to broad movers lists and circuit-breaker alerts before
  selecting two excerpts. This ranking does not establish causation. Full articles,
  filings and causality are not independently verified. No news
  for the entire batch means no AI call; missing evidence for an individual
  symbol must produce an unclear/insufficient result.

## Implementation and boundaries

`GET /api/market-pulse/snapshot` is read-only. `POST /api/market-pulse/analysis`
requires a server-captured snapshot ID and the current research provider hash.
Captures expire for new assessments after 15 minutes; ranking timestamps older
than four days or missing timestamps cannot launch an assessment. This allows
weekend review without mislabeling the prior trading session as live.

The assessment uses the existing isolated Codex brief worker with one model call,
its deadline, provider identity checks, and no API-key fallback. Only the exact
requested symbols are accepted. Catalyst citations must match an exact excerpt
from news for that symbol, with a 25-word-per-source quotation limit. The receipt
and evidence packet are saved in the existing brief store under `market_pulse`;
normal Explorer brief history excludes these records. Price snapshots themselves
are an in-memory, bounded cache. After an API restart, refresh prices before
starting a new assessment; saved assessments remain available.

This feature has no order submission or scheduling path. Auto-refresh is not a
streaming quote service. Subscription allowance can be consumed by an assessment;
provider timeouts have an unknown usage outcome and are not automatically retried.

## Verification

```sh
uv run --frozen --extra dev pytest tests/ui/test_market_identity.py tests/ui/test_market_pulse.py tests/ui/test_market_data.py tests/ui/test_explorer_briefs.py
npm --workspace apps/web test
npm run web:build
```

The automated tests cover arithmetic, feed separation, missing/invalid/stale data,
news cutoffs, citation validation, preserved evidence, isolated child dispatch,
HTTP lifecycle, cache behavior, and duplicate request recovery. Browser acceptance
also covers disconnected setup, top-ten analysis, source links, an unclear catalyst,
refreshing after analysis, table expansion, watchlist persistence, Research handoff,
keyboard navigation, reload recovery and desktop/narrow layouts. Populated browser
checks use explicitly labeled synthetic inputs. Those synthetic checks do not establish live provider access. A separate local
acceptance run on November 12, 2026 connected Alpaca market data and news through
an existing Keychain reference and completed two real Codex assessments using
`gpt-6.1-sol`. The final browser-triggered batch covered ten movers and passed
citation validation; saved results survived reload. Credentials, account settings,
news packets and screenshots remain local and are not distributed with the source.

Codex uses its managed runtime state location with ephemeral assessment threads.
Overriding `sqlite_home` to an empty directory stalled initialization on CLI 0.166;
that override was removed without changing the restricted permissions or tool
boundary. An opt-in runtime check starts no model turn:

```sh
TRADEMASTER_CODEX_SMOKE=1 uv run pytest tests/research/test_codex_research.py -k installed_codex
```

The selected-stock workbench was also checked against real Alpaca bars and asset
names and Yahoo company/ownership records. Browser checks covered exact warrant
identity, holder dates, missing parent data, chart ranges, stock switching, all
three dock positions, pointer dragging, keyboard resizing, saved preferences, reset
and narrow screens, with no AI requests triggered.

The dense-workstation revision uses 25-pixel scanner rows and a persistent chart.
Desktop acceptance checks measure actual pane sizes and viewport containment,
then exercise filtering, sorting, ticker linking, company tabs, resizing, docking
and reload at 2283x1222 and 1440x900, plus a 390-pixel mobile layout.
