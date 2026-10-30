# TradeMaster UX walkthrough — September 5, 2026

Follow-up implementation and current verification: [UX fixes](UX_FIXES_2026-09-05.md). The walkthrough below records the earlier audit state.

## Verdict

The main navigation and several complete workflows work. The previous UI overstated runtime readiness, provider connectivity, backups, and algorithm execution. Those claims and several functional defects were corrected during this walkthrough. This installation is not ready to describe every feature as connected or operational.

Normal installation inspected at `http://127.0.0.1:3000`, API `8797`. Mutating exercises ran against a separate temporary SQLite database, explicit in-memory broker, and web/API ports `3002`/`8798`. No order was submitted to the user's Alpaca account. No provider assignment, credential, model, baseline, or deployment was changed in the normal database.

## What the headline numbers actually mean

| Previous presentation | Verified meaning / corrected presentation |
|---|---|
| Runtime live | A runtime-configuration GET succeeded. Now “Configuration loaded,” with the read time. Worker health appears separately. |
| 20 providers | Twenty registered catalog entries; only five were enabled at inspection. These include disabled, planned, and experimental integrations. Enabled is not evidence of connectivity. |
| 4 snapshots | Four manifest-only records, zero encrypted backup artifacts. They cannot restore data. The header now separates these counts. |
| Provider Live / Test | Saved configuration and a local credential-availability check. Now “Enabled” and “Check credential,” with check time and “connection untested.” |
| Holdings Live | Holdings fetched from Alpaca paper when the view loaded, not a streaming feed. |
| Active trades Live | Saved local open-order statuses, some months old, not fresh broker reconciliation. |
| 27 algorithms, 6 categories | Real catalog entries for analytical deterministic plans. This does not mean 27 running trading systems. The manual exact-order ticket is a separate workflow. |
| Running algorithms, 4h since open | Saved program records plus a clock approximation that ignored weekends. Now a recorded-active count and actual record-read time. |
| Algorithm progress percentage | Previously invented from state names. Removed; unknown progress is “Not reported.” |

## Step-through results

| Surface / actions | Exercise and result |
|---|---|
| Primary navigation | Visited Portfolio, Research, Quant, Settings in the normal app. Added explicit selected-tab semantics. Control+4 navigation and Control+K/Escape command-palette open/close worked in the isolated browser. |
| Watchlist | Added and removed TSLA in isolated browser storage; symbols render unavailable prices honestly. Normal four-symbol quote display loaded. |
| Portfolio Overview | Inspected holdings, saved trades, old opportunity cards, research briefing, account/deployment links. Replaced misleading “Approve → Quant” wording with “Review in Quant”: this action opens a workbench, not an approval. |
| Positions / symbol drawer | Normal Alpaca positions loaded. Opened AAPL detail; quote/chart/news, recorded committee verdict, account position and links rendered. Removed “Live data” from a one-time response indicator. No buy/sell action was sent to Alpaca. |
| Watchers | Found genuine repeated alerts based on a zero-ask midpoint and yesterday's quote. Price watches now reject nonpositive, crossed, nonfinite, stale (>5 minutes), and future-dated quotes. Disabled watchers cannot record new fires. Manual checks only update the UI fire count when the API actually records a fire. Added real toast expiry, capped simultaneous alerts, and stopped replaying an hour of historical alerts on page open. Regression-tested valid and invalid observations; did not create/delete the user's watcher. |
| Performance: normal account | Opening baseline preview was rejected. Fresh broker equity was $100,821.86; cash plus detailed marked holdings was $100,821.855771, a $0.004229 discrepancy. Current micro-dollar reconciliation tolerance blocks enrollment. No baseline was approved and no balances were altered. |
| Performance: isolated account | Reviewed and approved explicit fixture baseline; reconciled account and outstanding orders. UI showed “Fixture simulation,” $0 investment P&L and zero fills. Reconciliation history, source-correction and deployment-return sections rendered; correction controls correctly remained disabled without source changes. |
| Symbol Research | Inspected recorded committee thesis, dated summaries, run-history/report affordances, and single/compare modes in normal app. AAPL/NVDA comparison charts, news, correlation and 21 matched observations rendered. Did not launch a metered remote committee run or export to an external observability service. |
| Strategy Research | Through UI: saved hypothesis, selected synthetic universe, froze version, used example dates, froze plan, loaded labeled synthetic data, queued/cancelled one attempt, queued another. Explicit one-shot local research worker completed the second. Inspected delayed-strategy result detail and all nine strategy/control/cost rows. Fixture status and negative results remained visible. |
| Research → Quant | “Review variant 1 in Quant” selected the matching completed experiment. Saved a fixture deployment draft. Missing reviewer reason and missing account baseline produced useful errors. After fixture baseline/reconciliation, prepared review: eligibility and actual-paper-provider checks failed and activation stayed disabled. |
| Algorithm workbench | Preview rendered an armed IOC plan. Corrected the misleading “Market buy/sell” label to “Triggered IOC.” Marked the $200 reference as a manual scenario input. Explained that hidden parameters use defaults and previews do not execute schedules. Advanced catalog expanded with 27 entries across six categories. Backend suite exercised every algorithm for both sides and determinism. |
| Exact paper ticket | In isolation: prepared one exact limit order, read account/quantity/limit/deadline, approved/submitted, observed accepted with zero fills, reconciled, requested cancellation, observed canceled and six history events. No algorithm scheduler was started. |
| Saved programs / intents | Removed console-only pause, stop and retry buttons; legacy records now say controls unavailable. Removed fabricated fill-progress bars. Preserved exact raw lifecycle labels, including partially-filled states. Changed “awaiting” to “saved unresolved” because accepted orders also appear in the list. |
| Settings Runtime | Loaded configuration and separate worker/data/model readiness. Changed runner mode in isolation and verified persistence. Runtime configuration is not a live provider probe. |
| Settings Providers | Added, enabled, checked credential, assigned a supported role, saved per-agent model overrides, reassigned and deleted a temporary custom provider through UI. Blank credential clearing is covered by API persistence regression. Unsupported bounded-research OAuth choices are disabled; server also rejects these assignments. Existing invalid assignments remain visible for correction. |
| Settings Backups | Created manifest and encrypted database backup in isolation; verified encrypted contents through UI. Missing-key verification displayed the actual backend error. Manifest records have no verify/restore affordance. Backup now uses SQLite backup API; independent decrypt/extract/integrity-check test verified committed WAL rows survive. Missing/corrupt backup files return verification failures. |
| Settings Developer | Toggled developer mode, downloaded JSON, used hard reload in isolation. Parsed downloaded JSON and confirmed temporary provider was included and backup key value was absent. Export is a settings/reference file, not credential migration or full workspace restore. |
| Partial outage | Forced snapshot-history GET to fail while other endpoints worked. Settings continued loading other panels and explicitly showed unknown snapshot history. Removed previous silent “zero snapshots” fallback. |
| Narrow layout | At 390px, initial Settings view overflowed to 488px and hid navigation. Fixed grid sizing, navigation and wrapping; rechecked screenshot and DOM width: no horizontal page overflow. |

## Functional fixes beyond wording

- Exact execution/accounting resolution now respects the selected broker role. Unconfigured or unsupported brokers return explicit errors; production no longer silently constructs a fake account. Test fixtures must be supplied explicitly.
- Clearing a saved credential reference now persists; omitting that field during a toggle preserves it.
- Local credential checks do not mark disabled providers as needing a key or claim network verification.
- New strategy research roles reject protocols without a supported bounded-call adapter.
- Backup snapshots contain a consistent SQLite image, including committed WAL state; hashes describe exactly the archived bytes.
- Duplicate snapshot-list route removed; manifest-only records no longer claim encryption merely because an encryption name was supplied.
- Verification clears an earlier success before retry, and provider/backup/watcher errors preserve useful API details.

## Remaining blockers and limits

1. **Normal strategy designer/extractor assignments use unsupported Codex OAuth.** The UI now explains this; no supported API provider was chosen on the user's behalf. The actual Astra completion path remains unverified. Existing model selections were preserved.
2. **Both durable research/deployment workers are offline in the normal installation.** The walkthrough ran only an isolated one-shot research worker. Engine availability does not mean a worker is running.
3. **Normal account baseline is blocked by sub-cent rounding.** Define a source-aware rounding/residual policy and test it through baseline, reconciliation, attribution and returns. Simply widening every reconciliation tolerance would obscure discrepancies; this audit did not do that.
4. **Legacy algorithm scheduling is not connected.** The simple and advanced catalog is analytical. Legacy pause/stop/retry had no implementation. Exact manually reviewed orders and the newer strategy-deployment pipeline are separate features.
5. **Backups cover the database only.** Research artifacts and referenced credentials are separate; no full workspace restore, offsite upload, scheduled backup or key recovery was proven.
6. **Remote capabilities remain unverified where unused.** No paid model completion, new provider subscription/entitlement, external trace export, genuine funded strategy activation, or provider-backed order/fill was exercised by this UX audit. No synthetic result is presented as investment evidence.
7. **Other user journeys still merit deeper acceptance:** all individual remote provider protocols, real dataset imports with entitlements, prospective funded deployment operation, and mobile layouts of every detailed report. This is a full major-workspace walkthrough, not a certification of every combinatorial state or integration.

## Validation evidence

- Initial focused backend pass: **87 passed** (snapshot/API/status/watcher cases).
- After broker-routing and credential-clearing changes: **86 passed** in the targeted API/accounting/deployment selection.
- Broad current run: **384 passed, 2 failed** across UI, all algorithms, and selected research lifecycle/provider tests. The failures are existing default-setting drift: `test_run_config_defaults_to_safe_report_only_mode` expects simulated but the pre-existing edited RunConfig defaults to real; `test_observability_service_exports_run_trace_to_langfuse` expects gpt-5.4/gpt-5.4-mini but the pre-existing edited defaults are gpt-5/gpt-5-mini. Those product defaults and unrelated tests were preserved.
- Final focused regression pass: **21 passed** (backup integrity, watcher validation, role compatibility, broker routing, credential clearing).
- Frontend: **160 passed** after final changes.
- Production build passed; remaining lint warnings concern pre-existing unused bindings in PerformanceWorkspace and ResearchWorkspace.
- Isolated and rebuilt normal browser JavaScript errors: **none** during checked flows. The user-facing preview was reloaded and verified displaying 20 catalog entries, 5 enabled, 0 backup files and 4 manifests; unsupported research roles and absent worker heartbeats remain explicit.
- Temporary evidence: `/tmp/trademaster-ux-audit/` contains screenshots, test/build logs, isolated database and encrypted test backup. Screenshots were visually inspected. Temporary files are not a production backup or permanent evidence archive.
