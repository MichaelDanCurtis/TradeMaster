# Paired guidance event outcomes

Verified 2026-09-05. This is software acceptance using synthetic datasets, not evidence of profitable trading or a completed release.

## Implemented behavior

Each preceding-arm comparison now retains every guidance notice available during the evaluation window in the dataset's timezone, plus notices referenced by actual outcomes. Repeated notices, abstentions, exclusions and proposed-but-unfilled entries remain visible. Issuer and forecast-period clusters identify dependence; repeated notices are not independent trials.

The attribution code independently reconstructs notice ownership from saved entry decisions and simulated fills. It applies whole-share splits, fractional-share cash compensation, dividend and delisting entitlements, fees and final valuations. Unpaid entitlements contribute once. Slippage remains inside fill prices. It verifies sale basis, every closing holding quantity, each event P&L identity and aggregate investment P&L plus account cash yield against the saved portfolio. Calculations use Decimal precision 36 and an absolute reconciliation tolerance of USD 0.00000001.

Outcomes distinguish closed, open, not filled and not entered. Open positions retain stale-mark counts and final stale status. A no-entry contribution of zero represents no owned investment P&L; it does not invent the return of a hypothetical rejected trade. Event contributions use initial portfolio capital as their denominator. Account cash yield and recurring model costs remain separate. These comparisons are neither causal selection estimates nor calibrated win probabilities.

Immutable event artifacts have an index and pages of at most 50 notices. Every page is registered in the experiment's artifact set. Publication verifies hashes, index/summary agreement, strategy-run provenance, contiguous page coverage, unique notice IDs and exact comparison coverage. Missing or inconsistent paired accounting prevents new guidance report completion. Legacy aggregate-only guidance reports remain readable but cannot qualify through the new paired-accounting promotion gate.

Research exposes each comparison and scenario, an event table, pagination and a full-width selected-event panel containing fill times, capital contribution, realized/unrealized P&L, income, fees, slippage, corporate actions and saved decision reasons. Requests are abortable; changing pages clears the selected details, and changing comparisons resets pagination. Keyboard selection focuses the detail panel.

## Verification

- Broad backend regression: **425 passed, 12 explicitly skipped native checks**, with one existing test-model warning. Log: `/tmp/trademaster-paired-regression.log`. This run preceded the final dataset-timezone boundary test.
- Final focused paired/guidance regression: **18 passed**. Log: `/tmp/trademaster-paired-finalfocused.log`. Cases include exclusions and repeats, actual cash yield, proposed/unfilled entries, stale open positions, independent corporate-action arithmetic, corrupted sale/holding data, page boundaries, missing/inconsistent publication pages and a New York late-evening notice stored on the next UTC date.
- Native LEAN: **3 passed, 9 deselected**, running all three guidance arms in actual offline containers and checking event attribution against local replay. Log: `/tmp/trademaster-paired-native.log`.
- Frontend: **160 passed** before the browser-driven detail-panel layout correction. The final production build, including that correction and keyboard focus handling, passed with four existing warnings. Logs: `/tmp/trademaster-paired-webtests.log`, `/tmp/trademaster-paired-webbuild-final.log`.
- Python compilation and tracked-diff whitespace checks passed. The checkout contains untracked implementation files, so tracked diff checks alone do not cover them.

The independent corporate-action case buys 19 shares at USD 100.05 with a USD 1 fee; a 1.5 split leaves 28 shares and USD 30 fractional compensation, followed by a USD 28 dividend entitlement and USD 1,960 unpaid delisting proceeds. Event investment P&L is USD 116.05 with USD 1,988 receivable. This is a hand-calculated correctness fixture.

## Browser and persistence evidence

The isolated database at `/tmp/trademaster-paired-ui/research.db` was seeded once and processed by the actual research worker. Strategy `strategy_55c10bbcab94457da2160d3ff3b75d87`, experiment `exp_59f23fef52514642a290a0f9be2e1deb`, name **Paired event evidence fixture**. The source fixture contains 16 in-window notices plus 53 explicitly synthetic repeated withdrawals to exercise pagination: 69 notices across four issuer/forecast-period clusters, displayed as 50 and 19 rows.

Verified comparison selection, next/previous pages, changing scenarios, event inspection, keyboard focus, clearing selection on pagination and resetting pagination on comparison changes. Restarted the API against the same database, rebuilt/restarted the production web app, reselected the strategy and reopened the saved comparison. No JavaScript exceptions, research alerts or page-width overflow were observed.

The Base-cost Astra-versus-numeric comparison retained its negative USD 59.8745 investment contribution difference. The one-off event was excluded by the challenger while its numeric control earned USD 30.37 net of two USD 1 fees. The detailed history retains the initial abstention, later exclusion and expiry, alongside the control's actual simulated entry and withdrawal exit. These deliberately synthetic outcomes demonstrate honest reporting, not market performance.

The initial browser walkthrough found long explanations inheriting table `white-space: nowrap`. The final implementation puts selected details above the table in a wrapping panel. Final screenshot: `/tmp/trademaster-paired-ui/details-final.png`; earlier screenshots document the issue. All screenshots were inspected. Browser and test API/web servers were stopped; ports 8797 and 3000 were clear afterward. No real provider/model/broker call or order was made.

## Remaining release requirements

Genuine labelled/prospective data acceptance, provider coverage and entitlement validation, positive genuine eligibility and the full funded release walkthrough remain outstanding. The broader implementation plan also retains provider-backed observation scheduling and protective-child/corrected-source accounting requirements. This change completes the paired accounting feature's synthetic and native correctness checks; it does not complete the whole implementation goal.
