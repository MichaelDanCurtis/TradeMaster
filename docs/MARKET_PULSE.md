# Market Pulse

Market Pulse is the default desktop workspace: a compact market overview with an
on-demand, source-linked explanation of the top five gainers and five losers.
Open it from the primary navigation or with Cmd/Ctrl+5. Existing shortcuts 1–4
remain unchanged.

## Use the desk

1. Configure **Alpaca market data** in Settings, including the desired snapshot
   feed. The board retrieves seven benchmark/asset ETF proxies, eleven sector
   ETF proxies, the top gainers and losers, and the volume leaders.
2. Select a mover to see its day range, day volume, opening gap, price relative
   to day VWAP, and bid/ask spread. Expand the tables to inspect up to 25 symbols
   on each side. Research and Watchlist buttons use the existing workflows.
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
uv run --frozen --extra dev pytest tests/ui/test_market_pulse.py tests/ui/test_market_data.py tests/ui/test_explorer_briefs.py
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
