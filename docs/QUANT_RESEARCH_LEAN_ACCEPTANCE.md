# LEAN execution and equity reference acceptance

Date: 2026-09-04. Engineering acceptance only. Synthetic inputs establish software behavior; they do not validate a strategy or authorize broker activity.

## Engine decision

Use the directly invoked open LEAN engine as an optional research executor. Retain the local Decimal replay for fast, deterministic checks. The API reports actual Docker/image availability; selecting an unavailable LEAN engine fails without substituting another result. Neither path grants broker authority.

The pinned image is `quantconnect/lean@sha256:8ba05f8a5425efb3b2d32299803a5d3bd5da953caf4597804b6763c8d9fa8736`. It was exercised on this arm64 host. The adapter requires Docker and that explicitly installed image; it never pulls an image, purchases data or creates a subscription. Containers have no network, no provider credentials, read-only input/source mounts, a bounded output mount and CPU/memory/process/runtime limits. Genuine data still requires its own provenance and entitlement; the image is not a market-data license.

The shared event-driven strategy/accounting kernel emits clock steps and venue operations. Local replay consumes them directly. The LEAN algorithm advances on custom, timestamped data and submits synchronous native market orders through LEAN's backtesting transaction handler. Actual native receipts drive the research fill ledger. Every closing cash, equity, receivable, holding quantity, fee total and cost basis is checked against the kernel. This is independent execution/account verification, not an independent implementation of the strategy hypothesis.

Input sessions determine opens, closes, holidays and after-hours observation wakes. Raw prices use stable instrument identifiers; historical mappings remain in the frozen dataset. Close prices are never exported at an earlier opening timestamp. Explicit split/dividend/delisting records drive a bridge to native holdings and settled/unsettled cash; bundled equity factor files and calendars do not determine research accounting. Fractional split quantities receive disclosed opening-price cash compensation. No intraday auction, spread, partial-fill or participation realism is claimed for this adapter.

Native accounting comparison tolerance is USD `0.000001` because custom Python data passes through floating point and .NET numeric values. Order price/fee reconciliation uses `0.00000001`; quantity is exact. Two fresh containers produce byte-identical canonical result artifacts for the pinned base fixture. Source files are hashed before copying, verified after copying and checked again inside the container. The evidence wire schema is frozen independently of the host/container Pydantic version; schema changes require an explicit revision.

Alternatives considered: local replay alone cannot exercise LEAN's transaction/portfolio machinery; a hosted/CLI workflow adds account/subscription and data dependencies; bundled daily equity data introduces factor precision and event-delivery conventions unsuitable as implicit authority for imported datasets. The custom-data adapter exposes those assumptions and keeps the runtime offline. Source timing follows LEAN's documented [custom-data end-time semantics](https://www.quantconnect.com/docs/v2/writing-algorithms/importing-data/streaming-data/custom-securities/key-concepts); simulated execution uses its [fill-model boundary](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/trade-fills/key-concepts).

## Correctness and recovery

The offline integration suite exercises trend plus all three guidance arms, a holiday/delayed order, missing prices, unaffordable opening gaps, splits with fractional compensation, delayed dividend payments, delisting and cash yield. The base independent calculation is three shares at USD 107.107 plus a USD 1 fee, ending at USD 1,004.679.

The durable worker also runs every trend control/scenario through actual containers. Cancellation removes the active container and prevents late publication. Killing the supervisor after a container starts closes its private monitoring pipe; the child exits through cleanup and removes the native container. The test verifies the actual Docker running state, not just local job status. Cleanup cannot be guaranteed when the Docker daemon itself is unavailable; normal lease recovery never treats an unfinished run as completed evidence.

Run explicitly from the repository root:

```sh
TRADEMASTER_TEST_LEAN=1 .venv/bin/python -m pytest tests/research/test_lean.py tests/research/test_reference.py -q
```

Ordinary research tests skip Docker integration unless explicitly enabled.

## Browser acceptance

An isolated database at `/tmp/trademaster-lean-ui/ui.db` and artifacts at `/tmp/trademaster-lean-ui/artifacts` were used. In the production frontend, the operator selected LEAN, chose a frozen plan/snapshot, queued the run while the worker was offline and inspected its completion. The report retained fixture-only status. After refresh and reselection, the base strategy detail exposed eight native order receipts and 65 native closing account records. Keyboard focus/Enter selected the run; DOM activation expanded its native-account disclosure. No research alert, JavaScript exception or document-width overflow was observed. An isolated browser stalled during a later screenshot and was restarted; the application servers remained healthy and the new browser completed verification.

- Strategy: `strategy_7ca3f9ce7f69450c8d7438e106f6ef1d`
- Experiment: `exp_e3bd21643ce14803ab23bf44e228bd1a`
- Report artifact: `afb64f05c8ea94514a3983e4f7bcc22566292ae600003a47a00a8ca5b8f75cda`
- Screenshots: `/tmp/trademaster-lean-ui/initial.png`, `queued.png`, `native-account-final.png`
- Logs: `/tmp/trademaster-lean-ui/api.log`, `web.log`, `worker.log`

## Equity-market reference

A plan can freeze a buy-and-hold reference instrument, initial allocation and rationale. It receives the same starting capital, calendar, cash yield and scenario costs, with its own disclosed allocation rather than the strategy's concentration caps. The initial quantity uses the first evaluated available close; the purchase is attempted at the subsequent scenario-adjusted opening window. It then holds without rebalancing or dividend reinvestment. Remaining funds accrue the same cash yield. Missing initial data or an unaffordable/missing opening window produces an explicit no-signal/unfilled outcome without a later automatic retry.

Reports retain all four paths for each scenario, show return and exposure differences versus the reference, and keep comparisons against the matched basket and preceding guidance arm. Equity differences are context, not risk-adjusted alpha, and outperforming equities is not itself a promotion criterion. A missing/unfilled/stale reference prevents complete paper-review evidence. Older frozen plans can still run as exploratory records; their missing reference is explicit.

The repository verifies complete variant/scenario/control coverage and equality with the frozen reference before accepting a report. Snapshot coverage is checked before charging a new trial. Hand calculations, delayed/missing inputs, opening gaps, action accounting, absent reference instruments and omitted report controls are tested separately from investment scoring.

The production browser froze a second plan with the reference enabled, queued it, and inspected the completed four-path comparison and reference detail. The synthetic base reference had one fill and a negative return; the unfavorable reference value was retained. Experiment `exp_027774fb13884f709b8c0124de4fd7e5`, plan `rp_12ff859022624491abc7bf7a7d13bdc1`, report `0f3a98972f235893a4fbe3f421668eb1d2aa71d558ce164d01189099829440bc`. Screenshots are `reference-result.png` and `reference-detail.png` in the same temporary directory. This flow used local replay; native reference execution was verified separately by Docker integration. Refresh/reselection retained both reports, the 12 reference-plan rows, nine older LEAN-plan rows, the frozen reference identity and the older plan's explicit missing-reference notice.

## Verification totals

- Research/model/provider/repository/room-policy Python suite: **153 passed, 12 explicit Docker skips**; `/tmp/trademaster-reference-final-regression.log`.
- Explicit offline LEAN plus reference suite: **21 passed**, including 12 native integration cases and nine export/reference checks; `/tmp/trademaster-lean-reference-native.log`.
- Full existing frontend suite: **160 passed**; `/tmp/trademaster-reference-webtests.log`. Six stale source assertions were reconciled with the existing four-room navigation, SSE event flow and removed builder/roadmap panels. These remain source-contract checks, not a substitute for browser acceptance.
- Production build passes with four existing nonfatal warnings; `/tmp/trademaster-lean-reference-build.log`.

## Early broker sizing correction

The Alpaca adapter now rejects a bracket/OTO budget below one whole share before resolving credentials or sending HTTP, validates positive finite quotes/notionals/protective prices, computes whole shares with Decimal arithmetic and rounds plain-order USD notionals down to cents. The existing GTC choice is preserved; its comment now correctly reflects that Alpaca documents both day and GTC. See [Alpaca order requirements](https://docs.alpaca.markets/us/docs/orders-at-alpaca).

Focused broker tests: **23 passed**, plus **6** existing constraint/execution-algorithm regressions. Logs: `/tmp/trademaster-broker-sizing.log` and `/tmp/trademaster-broker-context-regression.log`. This fixes sizing at the quoted price; actual market fills still require the plan's pending exact-approval, fresh-account, reservation and reconciliation work. No broker request was sent outside a recording test double.

The isolated browser sessions and API/web acceptance services were stopped after verification. Ports 3000 and 8797 were confirmed free; unrelated development services were left alone. No commits, real broker orders, paid model calls or purchases were made.
