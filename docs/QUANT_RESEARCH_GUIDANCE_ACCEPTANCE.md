# Guidance comparison acceptance

2026-09-04. This records a completed software milestone inside the still-active full implementation plan. It establishes no investment edge or broker readiness.

## Implemented behavior

- Same-forecast-period revenue guidance uses original normalized numbers, never an EPS surprise or model estimate. The most recent incompatible/withdrawn prior range cannot be skipped to manufacture an increase.
- Numeric quality requires positive current TTM revenue and operating cash flow and an improved cash-flow/revenue ratio relative to the preceding comparable TTM. Eight consecutive quarters are derived from quarter/YTD/annual disclosures. Overlapping YTD totals are differenced rather than added. Missing/conflicting reports abstain; later amendments cannot change past decisions.
- Frozen price/volume floors, reporting basis, financial age, event validity, excluded groups, holding horizon, portfolio caps and costs apply equally to all three arms. Cohort matching is enforced before the plan freezes and again in the worker.
- Source text and model response whitespace remain exact. The bounded classifier contract validates period, USD figures, current-document citation, source offsets, actual model/provider identity, prompt/schema hashes and input availability. Human labels never enter the model packet. Tool/order fields, malformed output, unavailable calls and invalid cost metadata are retained as failures/unknowns, not favorable fallback evidence. There is no automatic retry.
- Replay uses the first completed classification for an exact source packet; a newer material packet needs fresh evidence. The fixture's outputs and labels are hand-authored engineering data, never represented as real Astra calls.
- Each arm starts with equal capped allocations across the frozen universe. Exclusions leave cash. Quantities are fixed before a later opening window; repeats cannot add shares or reset the actual-fill holding clock. Explicit cuts/withdrawals and elapsed holding horizons produce exits. Missing opening bars produce one unfilled attempt; later invalid guidance can cancel a delayed pending entry.
- Event horizons, including stressed exit delay, are purged at evaluation boundaries. Uncertainty uses blocks at least as long as the holding horizon plus delay and remains undefined without enough independent blocks. Repeat announcements count once per issuer/forecast period for the frozen evidence threshold.
- Reports show cash/fixed-basket/strategy paths for every scenario, then numeric versus guidance and evidence versus numeric comparisons. Preserved extraction charges include unused/failed attempts and remain separate from broker/trading cash accounting. Human-label accuracy/confusion and its Wilson lower bound are reported separately from investment returns. Historical classifier evidence is exploratory and cannot satisfy the prospective-classifier gate.

## Verification

Command from the repository root:

```sh
.venv/bin/python -m pytest tests/research tests/ui/test_repository.py tests/ui/test_room_policy.py -q
```

Final result: **118 passed in 11.72 seconds**; output `/tmp/trademaster-guidance-tests.log`. The suite includes the existing trend/accounting/worker regressions and new guidance, extraction, timing, labels, cohort and atomic API batch tests. Production `npm run build` passes; log `/tmp/trademaster-guidance-build.log`. The four previously recorded unrelated lint warnings remain. The six previously recorded obsolete frontend source-test failures have not been claimed as resolved.

The full guidance worker test registers a durable plan/snapshot, consumes nine family trials, executes a real child process, verifies all artifact hashes, returns 27 run summaries and six incremental comparisons, and retains every fixture verdict as `fixture_only`.

Browser acceptance used an isolated database `/tmp/trademaster-guidance-ui/ui.db` with real runs disabled and dotenv loading disabled. The flow created a hypothesis, selected the labelled universe, froze three versions atomically, froze a plan with the example dates and a zero-session boundary embargo, loaded the labelled dataset, selected the 2020 holdout, queued while the worker was offline, ran `worker --once`, and watched the completed report arrive. Simulated capital was $10,000. Keyboard focus/Enter was used for actions.

Records:

- Strategy: `strategy_511b0b1ff6744123bc9b6914b358a004`.
- Experiment: `exp_3de4d0f071b2440ea619b715fb2ce4f0`.
- Report artifact: `7aa66c7073a5e2261088fcf044ae273eb2b93ff5e889b2d7c1d39d6187900781`.
- Final screenshots: `/tmp/trademaster-guidance-ui/final-comparison.png`, `/tmp/trademaster-guidance-ui/final-labels.png`; earlier detail capture `/tmp/trademaster-guidance-ui/decisions.png` predates the grid-width fix.

The browser exposed two integration defects, both repaired and rechecked: display-only schema fields leaking into a strict freeze request, and a grid item's minimum width letting evidence tables stretch the report. The final report width was 637 pixels within a 683-pixel main column; its 818-pixel comparison table scrolls inside that panel. Reloading the production app retained the completed report. There were no JavaScript exceptions, error overlays or research alerts after the fixes. Unconfigured watchlist quotes remain unrelated unavailable-provider output.

The synthetic base path bought four issuers in the guidance control, three with numeric quality, and one with cited evidence. The evidence arm's incremental return was negative versus the numeric control and remains negative in the report. The eight hand-authored labels matched, with a 67.56% Wilson lower bound; neither the tiny label set nor fixture returns qualify for promotion. Browser, API, web server and one-shot worker were stopped after acceptance.

## Remaining work

At this milestone, configured model dispatch, durable call-cost reservations/attempts and role routing were still required. The subsequent [model dispatch acceptance](QUANT_RESEARCH_MODEL_DISPATCH_ACCEPTANCE.md) implements those boundaries and verifies them against local HTTP servers through the installed SDKs. Imported evidence costs remain preserved snapshot claims, and newly metered costs use operator-frozen token rates rather than verified invoices. Genuine historical/prospective sources and independent labels remain absent.

The full LEAN adapter/parity work, simple equity reference, event-outcome/calibration audit, deployment/approval/reservation/unknown-submission handling, persisted real accounting, full release verification and separately approved provider-paper smoke remain in the overall plan. No broker order or paid model call was made in this milestone.
