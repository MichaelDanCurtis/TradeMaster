# TradeMaster: executable research and personal quant strategies

Date: 2026-09-04. Status: proposed implementation design, based on the current working tree and the user's accepted product direction. This document specifies future behavior; it is not evidence that these features are implemented or that either strategy is profitable.

TradeMaster should let an individual investor investigate an economic idea, measure it honestly, allocate bounded capital, and explain subsequent outcomes. Astra designs and challenges research. Deterministic software calculates signals, evaluates evidence, manages portfolio targets, and executes approved instructions.

The first release proves that this workflow works with a diversified trend baseline and a guidance-and-cash-quality challenger. It does not require a positive investment result: a reproducible rejection is a successful research outcome.

Implementation sequence: [QUANT_RESEARCH_BUILD_PLAN.md](QUANT_RESEARCH_BUILD_PLAN.md).

Architecture: [interactive PrixmaViz workspace](https://prixmaviz.ailuxis.com/w/96856d31-aae0-4cbe-b72a-8476eeae6825). Diagram ID: `d_04ff6b0ff03941fd`; follow-ups should update that diagram. Local source: [quant-research.mmd](diagrams/quant-research.mmd).

## 1. The user experience

An investor enters: “Investigate whether raised revenue guidance accompanied by improving cash generation predicts subsequent returns.” The Research workspace turns the request into a testable hypothesis, shows missing evidence, and offers a bounded experiment. The results explain whether the idea improved on its control after costs, what failed, and what remains uncertain.

| Existing surface | Addition | Primary user decision |
| --- | --- | --- |
| Research | Strategies view alongside existing symbol research; hypothesis editor, evidence sources, trial history, baseline comparison | Revise the hypothesis, freeze a test plan, or request paper review |
| Quant | Portfolio strategy deployments above existing symbol execution programs | Review capital, approve paper orders, pause, or retire |
| Performance | Historical equity, reconciled fills, cost attribution, control comparisons | Continue observation, reduce risk, or propose a new version |
| Brief | Material experiment completions, data gaps, paused strategies, reconciliation exceptions | Resolve the next actionable item |
| Settings | Data capabilities, quant runner health, research budgets, model version | Configure the resources a strategy actually needs |

A strategy page answers five questions before presenting detailed metrics: What is the idea? What evidence supports it? How can it lose? What would invalidate it? What happens next?

Show explicit evidence states: `fixture only`, `historical exploratory`, `locked historical evaluation`, `prospective shadow`, and `broker paper`. Display `insufficient evidence` as a valid outcome. Never turn unknown performance into zero or fabricate example returns in an account view.

Keep strategy logic, portfolio sizing, and execution methods distinct. TWAP/VWAP are execution choices; Kelly and volatility scaling are sizing concepts; earnings and trend signals are hypotheses about returns. A catalogue entry does not imply validated alpha.

## 2. What the existing code supports

Paths below are relative to the TradingAgents repository. Findings are from source inspection, not an end-to-end runtime audit.

| Current implementation | Preserve | Extension or limitation |
| --- | --- | --- |
| `apps/web/src/components/ResearchWorkspace.tsx` | Symbol research and its handoff to Quant | Add a portfolio-aware strategy view; research is currently symbol-first |
| `apps/web/src/components/QuantWorkspace.tsx` and `QuantWorkbench.tsx` | Catalogue, intent queue, paper execution surface | Add parent strategy deployments; maintain existing manual workflows |
| `tradingagents/algorithms/base.py`, `registry.py`, `trader_bridge.py` | Pure plan construction and existing callers | Introduce a separate signal/target contract; a supplied side is not a computed signal |
| `tradingagents/ui/models.py` | Theses, funding reviews, programs, orders, ledger records | Programs currently carry one required symbol; add a deployment parent and linkage records |
| `tradingagents/ui/repository.py` | Existing persistence methods | Add focused research repositories instead of expanding the monolithic repository indefinitely |
| `tradingagents/ui/brokers/service.py` | Paper broker boundary, approval records, order IDs | Revalidate current constraints at submission; add atomic reservations and recovery |
| `tradingagents/ui/constraints.py` | Deterministic veto mechanism | Current checks use simple notionals; add cash, pending orders, account freshness and reducing-risk semantics |
| `tradingagents/ui/trigger_harness.py`, `watchers/` | Deterministic wakeups and events | Wake a deployment evaluator; do not treat a trigger as order authority |
| `tradingagents/graph/role_models.py` | Role-based model routing | Record actual provider/model/prompt revisions; add research-designer role plumbing |
| `apps/web/src/components/PerformanceWorkspace.tsx` | Existing account display | Persist real equity history and cash flows before calculating time-series returns |
| `tradingagents/ui/db.py` | SQLModel/SQLite foundation | `create_all` is not a migration system; prefer additive tables initially and test upgrade paths |

The working tree has extensive pre-existing changes. Implement additive slices and inspect each diff before committing. The user reports no production data, but development state and unfinished work should still be preserved.

### Readiness issues to resolve before broker-paper promotion

- The fundamentals filter in `dataflows/alpha_vantage_fundamentals.py` filters fiscal period ends, not publication availability; `get_fundamentals` does not apply the supplied historical date. These paths cannot substantiate point-in-time research as written.
- `algorithms/event_driven/earnings_drift.py` assumes positive surprise and raised guidance when inputs are absent. `volatility/kelly_fraction.py` defaults a win probability. Such defaults remain labelled preview assumptions and must not satisfy research or execution prerequisites.
- `mean_reversion/pair_spread.py` builds legs from supplied inputs; it does not estimate or validate the economic/statistical relationship. Its legs also require explicit gross-capital accounting.
- `ui/api.py::_default_constraint_context_provider` can fall back to synthetic equity and zero exposure. Strategy deployments require fresh account facts and must reject these fallbacks.
- The inspected `BrokerService.submit_approved_order` checks mode/status/approval but does not re-evaluate the current symbolic constraint context immediately before submission.
- `ui/brokers/alpaca.py` uses `max(int(notional // current_price), 1)` for bracket quantity. A budget below one share can therefore produce an oversized order. Reject sub-minimum orders; do not round up through a capital cap.
- `volatility_targeting.py` can increase proposed notional above the input notional. Final portfolio limits must apply to actual proposed quantities and all legs after every transformation.

## 3. Architecture decisions

### Astra and deterministic execution

Astra proposes hypotheses, extracts evidence into a bounded schema, critiques experiments, and explains results. A model's stated confidence is not a calibrated return forecast or win probability. Broker credentials, approval grants and mutable portfolio limits are unavailable to research workers.

In v1, Astra fills validated strategy templates and proposes parameter changes; arbitrary model-generated Python is not automatically executed. Later code synthesis can use a reviewed, isolated build process with no secrets and bounded resources. Model changes, prompts, parameters and material feature changes create new strategy versions.

Quant evaluation consumes a frozen strategy and frozen data. Both replay and prospective operation call the same deterministic feature and target functions. Fresh Astra evidence can be an input only through the pinned extraction schema, timestamp rules and missing-data behavior established before deployment.

### Execution engine decision

Evaluate LEAN first through an adapter. Keep the existing BrokerService as the sole paper order writer for this release. A LEAN research/replay worker gets no brokerage credentials and returns targets, simulated fills, metrics and manifests. A separate TradeMaster deployment evaluator uses shared strategy logic on current data and passes target deltas through approval and risk checks.

This is a proposed integration contract, not an already-supported one-click LEAN feature. The adapter spike must prove target export, calendar semantics, corporate-action handling, replay/prospective parity and reproducibility. Pin the engine image/build. Record data and model versions separately.

LEAN CLI supports local/container backtests; custom fill and slippage assumptions still need explicit configuration. Verify current licensing, subscription requirements, data entitlements, Docker and machine compatibility during the spike. `backtrader` is already declared in `pyproject.toml`; dependency presence alone does not establish a usable research pipeline. If LEAN is unsuitable, record the failed criterion and evaluate an alternate adapter without changing the domain contracts. [LEAN deployment](https://www.quantconnect.com/docs/v2/lean-cli/backtesting/deployment), [slippage modeling](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts)

### Storage and jobs

Keep transactional metadata in SQLite initially. Store immutable larger artifacts in a configurable local research directory, addressed by content hash; use Parquet for tabular history and JSON for manifests. Persist an experiment row before dispatch, then claim work using a lease/heartbeat and a unique job key. A crash leaves recoverable state, not a disappearing experiment. One local worker is sufficient initially.

The application remains usable when the runner is unavailable. A queued job reports `runner unavailable`; it never fabricates a completed result. Data and compute budgets are enforced by the worker controller, including all model calls and retries.

## 4. Domain contracts

These are proposed typed contracts. Validate identifiers and associations server-side; do not accept client-supplied lifecycle state as authority.

| Object | Required meaning |
| --- | --- |
| `StrategyDefinition` | Stable identity, economic rationale, owner, supported universe, current draft/version references |
| `StrategyVersion` | Immutable rule schema; feature, code and prompt hashes; actual model/provider ID; timing; sizing; benchmark; unknown-input behavior; parent version |
| `DatasetSnapshot` | Provider, license/entitlement reference, stable instrument IDs, coverage, calendar/time zone, normalization rules, availability/revision provenance, artifact hashes |
| `ResearchPlan` | Frozen hypothesis family, all planned variants, trial/compute limits, development/validation/holdout dates, metrics, cost scenarios and promotion criteria |
| `ExperimentRun` | Version and snapshot IDs, research-plan ID, attempt/parent IDs, seed if relevant, engine build, state, start/end, failure reason, resource costs and result hashes |
| `EvidenceObservation` | Fact or classification, source passage/hash, value/units/period, publication time, ingestion time, processing completion, extraction version and validation result |
| `SignalObservation` | Version, instrument, decision time, input snapshot hashes, signal, validity horizon and explicit no-signal reason |
| `PortfolioTarget` | Deployment, evaluation ID, instrument, desired quantity/weight, cash reserve, current holdings basis and expiry; portfolio targets are evaluated together |
| `PromotionReview` | Frozen evidence report, gate outcomes, reviewer, funding/mandate references, policy version, decision and reason |
| `StrategyDeployment` | Frozen strategy version, paper account, capital envelope, lifecycle, reconciliation state; links to existing child programs via an additive join table |
| `ExecutionAttempt` | Idempotency key, target/intent/broker links, approval hash, reserved cash/exposure, submitted quantities, unknown/rejected/filled state |
| `EquitySnapshot` / `CashFlow` | Account and strategy attribution, timestamps, cash/positions/liabilities, external flows, fees, income and reconciliation provenance |

A content hash identifies exact inputs; it does not prove those inputs are correct. Dataset corrections create new snapshots. Reports include both hashes and human-readable provenance.

Use explicit units: return fractions versus percentages, USD versus other currencies, shares versus notionals. Financial ledger values use decimal precision and rounding at instrument boundaries. Stable instrument IDs survive ticker changes; display tickers are labels.

### Lifecycle

Strategy versions are immutable artifacts. Research jobs move through `queued`, `running`, `completed`, `failed`, or `cancelled`. Completion never means the strategy passed.

Evidence reviews return `insufficient_evidence`, `rejected`, `revise`, or `eligible_for_paper_review`. Eligibility does not arm anything. A human records the funding decision and paper-deployment approval.

Deployments move through `draft`, `paper_review`, `paper_active`, `paused`, `retired`, or `failed`. Activating, resuming, changing capital and retiring are recorded actions. An active deployment remains pinned to its version. No lifecycle transition enables live mode in this release.

Initially retain the existing approval requirement for each broker-paper order. Strategy-level unattended authority is a later feature requiring a separate reviewed mandate implementation. A research completion or market trigger cannot implicitly approve an order.

Pausing blocks new risk and attempts to cancel unfilled entry orders. It does not silently liquidate holdings or remove protective orders. Show cancellation acknowledgement and residual exposure. Exposure-reducing exits have a separately defined policy so a drawdown pause cannot accidentally trap positions. Resume requires reconciliation and renewed human approval.

## 5. Point-in-time research

Every observation records `event_time`, `published_at`, `ingested_at`, `processed_at`, source revision, and `available_at`. Live availability is no earlier than publication, actual receipt and required processing completion. Historical replay uses defensible historical publication/availability plus a declared latency model; it does not confuse today's download time with historical availability.

For bars, a closing-bar signal is usable only after that bar completes and arrives. For filings, a fiscal end date is never sufficient. An amendment is a later observation, not a replacement of what the strategy knew originally. If historical availability cannot be established, exclude the observation from validated historical evaluation and label it accordingly.

Preserve corporate actions, delistings, trading halts, security mappings, original releases and revision history. Define adjusted signal prices separately from actual tradable prices and ledger cash flows. Do not double-count dividends through both adjusted-price returns and cash credits.

Both event and price pipelines reject future records, duplicate events, incompatible units and stale inputs. Missing required evidence yields `unknown` or `no_signal`, never a favorable default. Public filings can seed the data layer; timestamped analyst expectations and licensed transcript archives are separate capabilities. [SEC APIs](https://www.sec.gov/search-filings/edgar-application-programming-interfaces)

Historical documents supplied to an LLM do not remove possible knowledge of subsequent events embedded in model training. Historical LLM results are exploratory unless contamination can be meaningfully controlled; independently timestamped prospective evaluation is required to support incremental-value claims.

## 6. First strategy: diversified trend baseline

Research candidate `diversified_trend_v1`. The constants below are a declared starting experiment, not optimized recommendations or personalized capital allocations.

- Universe: a versioned, predeclared set of liquid, unlevered ETFs covering US equities, developed international equities, intermediate Treasuries, inflation-linked Treasuries and gold. Select exact instruments from provider coverage before freezing the plan. Do not claim historical commodity/futures diversification from an ETF-only test.
- Use a fixed basket for this prototype, evaluated only during actual instrument availability; disclose selection bias from choosing today's funds. Dynamic historical-universe claims require membership history and delistings.
- Signal: after a completed session, calculate total-return momentum over 63, 126 and 252 sessions. Each positive lookback votes one, otherwise zero. The score is the fraction of positive votes. Require complete warm-up; no forward fill across missing trading observations.
- Sizing: score divided by trailing 63-session annualized volatility, with a predeclared minimum volatility floor and risk-group caps. Normalize positive scores to at most the deployment budget, cap positions, and leave unallocated capital in cash. Do not re-inflate remaining names after caps. No leverage or shorting in v1.
- Rebalance weekly using information available after the final trading session of the week. First eligible execution is a specified window in the following session; replay uses that window's observed prices and costs, never the prior close. Define holiday/calendar behavior in the plan.
- Exit/reduce when the score or target falls, with turnover and liquidity limits. Rejected or delayed orders leave actual positions unchanged; recompute targets from actual holdings next time.
- Controls: cash with actual modeled account yield and a fixed-weight version of the same ETF basket, with the same capital, dates, data and trading-cost model. Also show an equity-market reference, but do not label every difference versus equities as alpha.
- Failure analysis: whipsaws, sharp reversals, correlated bond/equity declines, concentration, cash drag and cost sensitivity.

Compute a portfolio covariance-based risk estimate to report exposures; do not call inverse-volatility weighting full portfolio volatility targeting. Risk budgets and position caps are research-plan inputs that must be explicit before execution.

This baseline tests the infrastructure and provides a comparison. Long-horizon trend evidence motivates research but does not validate this particular rule or ETF set. [AQR trend research](https://www.aqr.com/-/media/AQR/Documents/Insights/Journal-Article/AQR-JPM-Fall-2017.pdf)

## 7. Second strategy: guidance revisions and cash quality

Research candidate `guidance_cash_quality_v1`. Start with liquid US nonfinancial operating companies. Exclude financials and REITs because this initial cash-quality definition is not comparable across those businesses. Freeze liquidity criteria and universe construction before evaluation.

An event qualifies only when numeric revenue-guidance midpoints increase for the same forecast period, currency and reporting basis relative to the previous publicly available guidance. Missing comparable prior guidance is `unknown`. Guidance is distinct from analyst-consensus earnings surprise; the prototype must not label it an EPS beat.

The deterministic quality filter requires positive trailing-twelve-month revenue and operating cash flow, with operating-cash-flow/revenue improving versus the comparable prior-year trailing period. Derive quarters consistently from cumulative reports, preserve restatement availability, and reject incompatible or incomplete comparisons. This is a simple testable definition, not a universal measure of earnings quality.

Astra extracts guidance passages and classifies whether improvement appears dependent on a disclosed one-time item, a reporting-basis change or an unresolved contradiction. Output is a bounded enum with cited passages and an explicit `unknown`. Numeric arithmetic and period comparisons are independently checked. The same source snapshot feeds every arm.

Run three preregistered arms:

1. **Guidance control:** qualifying guidance increase, no quality filter.
2. **Numeric quality:** guidance control plus the deterministic cash-quality filter.
3. **Astra challenger:** numeric quality plus the pinned evidence classifier's eligible/unknown rule.

The Astra contribution is arm 3 versus arm 2; arm 2 versus arm 1 measures the numeric filter. Separately score extraction accuracy against human-labelled events, including excluded/unknown examples. Astra does not grade its own answers.

Entry is the next regular-session execution window after all required evidence is available and processed. Planned exit is after 30 trading sessions, or an earlier observed guidance withdrawal/cut for the same period. A second event while already invested may reduce or exit but does not pyramid or restart the holding clock in v1. Delisting, halts and unfilled exits are modeled explicitly.

Use identical position-sizing rules, caps, cash treatment and execution assumptions for all arms. Show both portfolio results and paired event outcomes, including the effect of differing exposure and abstentions. Sector/market comparisons supplement these controls. No hindsight removal of bad events.

The first data deliverable is a small labelled replay fixture with publication and amendment edge cases. Synthetic or hand-selected examples prove mechanics only. Broad historical evaluation needs genuine universe/event coverage; paper testing begins only after the operational prerequisites and explicit approval.

## 8. Evidence requirements

Freeze the research plan before evaluation: economic mechanism, hypothesis family, trial budget, temporal splits, horizon, eligible inputs, controls, metrics, cost scenarios and acceptance rules. Exact dates depend on data coverage and must be recorded before results are inspected.

Walk forward in chronological order. Fit transforms on training data only. Purge overlapping outcomes at split boundaries and apply an embargo appropriate to the holding horizon. Reserve a final unseen period; once inspected, it cannot remain an untouched holdout for revisions. Record failed, cancelled and manually revised trials in the same hypothesis family. Charge every inspected variation to the trial ledger.

Report net return, volatility, drawdown and duration, downside/tail outcomes, turnover, exposure, number of independent events, cost breakdown, concentration and benchmark-relative results. Include uncertainty intervals with resampling that respects temporal/event dependence. Distinguish economic significance from statistical significance. Correct for search/selection where applicable; a deflated Sharpe calculation is a diagnostic, not a universal promotion threshold. [Deflated Sharpe research](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)

Report base costs, doubled execution costs and an additional execution-window delay. Use observed spreads/volume when available and disclose any calibrated assumptions. Include model calls, data subscriptions and compute in operating economics; separate research startup cost from recurring deployment cost. Do not book hypothetical costs as actual broker cash movements.

Paper eligibility requires complete lineage, valid inputs, coherent accounting, no unresolved leakage findings, and a reviewed evidence assessment under the predeclared criteria. No single Sharpe cutoff or fixed number of days can establish an edge. Prospective sample requirements depend on event frequency, dependence and the size of improvement being tested; limited samples remain inconclusive.

Maintain separate operational and economic gates. A broker-paper run tests order behavior and ongoing observations; it cannot establish realistic market impact. Alpaca documents that its paper simulation omits important live effects. Show broker-paper fills and conservative cost-adjusted analysis separately. [Alpaca paper trading](https://docs.alpaca.markets/us/v1.4.2/docs/paper-trading)

## 9. Portfolio execution and accounting

A deployment owns portfolio targets and creates existing symbol-level execution programs. An additive link table preserves the current required-symbol contract. Prevent two deployments from spending the same cash by reserving buying power and pending exposure atomically at account level. Include manual positions, other deployments, open orders and unacknowledged cancellation requests.

V1 processes a rebalance serially: risk-reducing sells first, then buys against broker-confirmed available buying power. It does not presume unsettled proceeds are usable. Validate permissions and instrument eligibility, current data, whole/fractional share constraints, minimum size, final quantities, budget and post-trade exposures immediately before submission.

Persist an execution attempt before the broker call, with a stable idempotency key and approval bound to the exact order proposal. Changed quantity, instrument, side or material terms require a new review. On timeout, mark submission `unknown` and reconcile by client order ID before any retry. Do not treat every network exception as a definitive broker rejection. Use a single account writer/lease and transactional claims; database uniqueness plus broker reconciliation must survive crashes and duplicate wakeups.

Track partial fills, rejects, replacements, cancellations and late/out-of-order updates. Reconcile broker cash, positions and orders on startup, reconnect and periodically. Unknown account state suspends new entries. Record every state transition and observed discrepancy.

Persist daily and event-driven equity snapshots with external deposits/withdrawals separated from investment P&L. Include dividends, cash interest, fees and corporate actions without double counting. Calculate time-weighted performance for strategy comparison; money-weighted investor results can follow when cash-flow coverage is sufficient. Account equity is reconciled independently of strategy attribution; manual trades and shared holdings need explicit allocation rules.

For v1, prefer an isolated paper account and explicit attribution of each execution attempt. A strategy's drawdown threshold is an intervention rule, not a guarantee that gaps cannot exceed it. Sell-to-reduce handling must be defined before blocking all activity on drawdown.

## 10. Completion and later expansion

The first complete demonstration lets an operator create and freeze a hypothesis, run a reproducible experiment, inspect all attempts and missing data, compare a control with a challenger, and request paper review. With configured paper providers and approval, the operator sees a real paper order, reconciled fills, persisted equity and an explanation linked back to the exact strategy version. Restarting the worker does not duplicate the order.

Fixture replay and broker-paper completion are separate milestones. A fixture, catalogue preview, passing unit test or green backtest is not evidence of a completed deployment or profitable strategy.

Later research can add relative value, futures trend/carry, and selective option premium strategies after their instrument models, costs and portfolio controls exist. Income planning should translate requested withdrawals into required returns, reserves and drawdown exposure; it should not promise monthly distributions from uncertain trading profits. Tax-aware results depend on the investor's jurisdiction and account details.

Open user inputs for later capital calibration: deployable amount, desired withdrawals, acceptable drawdown, account/jurisdiction, permitted instruments and automation preference. None is required to implement the evidence foundation. No live trading, funding movement, paid data purchase or unattended authority is authorized by this design.
