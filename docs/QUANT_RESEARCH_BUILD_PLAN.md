# TradeMaster quant research: build sequence and acceptance

Date: 2026-09-04. Software implementation accepted locally on 2026-09-05; see [release audit](QUANT_RESEARCH_RELEASE_AUDIT.md) for the requirement mapping, final checks and separate unestablished research/provider-paper milestones. Requirements below remain the release contract. Detailed history is in [QUANT_RESEARCH_IMPLEMENTATION_STATUS.md](QUANT_RESEARCH_IMPLEMENTATION_STATUS.md).

Design and rationale: [QUANT_RESEARCH_DESIGN.md](QUANT_RESEARCH_DESIGN.md).

The release target is one traceable path from a hypothesis through honest evaluation to approved paper execution. Build the evidence foundation first. Keep work additive because this checkout already contains substantial uncommitted work.

## Slice 1 — immutable strategy and experiment records

User outcome: Research can save a hypothesis, freeze a strategy version and test plan, and show its complete experiment history after restart.

Proposed new files:

- `tradingagents/research/contracts.py`: typed strategy, snapshot, plan, observation and result contracts, with explicit units and validation.
- `tradingagents/research/models.py`: additive SQLModel tables for definitions, versions, plans, snapshots and experiments.
- `tradingagents/research/repository.py`: focused CRUD, immutable version creation, trial registration and lifecycle transitions.
- `tradingagents/research/api.py`: router with create/list/read, freeze and queue operations.
- `tests/research/test_contracts.py`, `test_repository.py`, `test_api.py`: boundary and persistence tests.

Integration: import new models in `ui/db.py`; include the router from `ui/api.py`; add read/draft/research-run grants in `ui/room_policy.py`. Do not grant broker permissions. Reuse the current approval ledger for eventual promotion decisions.

Proposed API surface:

| Method and route | Behavior |
| --- | --- |
| `POST /api/research/strategies` | Create an editable hypothesis draft |
| `POST /api/research/strategies/{id}/versions` | Validate and freeze an immutable version |
| `POST /api/research/plans` | Freeze variants, budget, splits, costs and criteria |
| `POST /api/research/experiments` | Register a trial and queue it; never return fabricated results |
| `GET /api/research/strategies/{id}` | Definition, versions and linked evidence |
| `GET /api/research/experiments/{id}` | State, manifest, metrics or explicit failure |
| `GET /api/research/strategies/{id}/experiments` | Every trial, including failed/cancelled attempts |

Acceptance:

- Frozen versions/plans cannot be edited; a revision gets a new ID and parent link.
- Invalid units, future split ordering, missing required policy and unsupported rules are rejected.
- Repeated requests with the same idempotency key do not create duplicate jobs; materially different payloads conflict.
- Research cannot set `paper_active`, approve itself, select live mode or invoke broker submission.
- A legacy SQLite fixture upgrades without losing existing tables/records; `create_all` is not used to pretend old columns migrated.
- UI renders a true empty state and persisted drafts; no synthetic performance.

This is the first implementation boundary. It needs no paid data, broker credentials or LLM access. It establishes identity and provenance, not investment validity.

## Slice 2 — data snapshots and timing guarantees

User outcome: each experiment identifies exactly which observations were available at each decision time.

Add `tradingagents/research/data/` for manifests, instrument/calendar mappings, immutable storage, availability queries and fixture loading. Connect provider adapters only after validating their timestamp and corporate-action semantics. Existing current-fundamental APIs remain advisory until they meet this contract.

Acceptance fixtures cover a filing published after quarter-end, an after-hours release, a later amendment, a ticker change, split/dividend accounting, a missing bar, duplicate ingestion, and an unavailable prior guidance value. Asking for a snapshot before publication cannot reveal the later fact. No required input is replaced by a favorable default.

Persist source units and original values before normalization. Downloaded history without historical availability receives an explicit coverage limitation. Runtime checks reject a snapshot whose contents no longer match its manifest.

## Slice 3 — quant adapter and trend baseline

User outcome: the trend specification runs deterministically and produces a reconciled evidence report against its controls.

Add `tradingagents/research/engines/base.py`, `engines/lean.py`, `strategies/trend.py`, `worker.py`, and `metrics.py`. Shared strategy functions accept observations and holdings and emit targets; they do not import broker services. Use tiny offline fixtures for correctness, distinct from genuine market evaluation.

Before selecting LEAN, run one bounded spike: pin a runner build, execute an offline fixture, export targets/fills, verify custom cost assumptions, restart it, compare shared-function outputs and record runtime/data-license requirements. Record the decision and alternatives. Do not install a subscription or purchase data as part of the spike.

Acceptance:

- Identical immutable inputs/build produce matching deterministic artifacts within declared numeric tolerances.
- A signal using Friday's close cannot receive a Friday-close fill.
- Warm-up, holidays, splits, dividends, fees and unfilled orders reconcile to independently calculated fixtures.
- Position caps, group caps and cash reserve hold after rounding; no accidental leverage.
- A zero-trade strategy, zero variance and insufficient history report valid unknown/undefined metrics rather than NaN or misleading Sharpe.
- The worker has a bounded queue, lease recovery, cancellation and persisted failure; unavailable engine means unavailable experiment.
- Trend and control use the same investable dates and cost assumptions. Parameter tuning does not reuse a consumed holdout.

## Slice 4 — earnings evidence and Astra comparison

User outcome: the operator sees whether Astra's evidence classification adds value over the numeric quality filter.

Add `strategies/guidance_quality.py`, `evidence/extraction.py`, `evidence/validation.py`, `evaluation/comparison.py`, and source/label fixtures. Extend existing model routing to resolve a research-designer/extractor role and persist actual provider/model IDs, prompt hashes, outputs and call costs. Do not assume that a desktop model name is a valid project API model ID.

Acceptance:

- Three arms match the design: guidance-only, numeric-quality, and Astra challenger.
- Model output is constrained to known fields; malformed evidence, missing passages and incompatible periods abstain.
- A source passage cannot override system instructions or invoke tools; extraction output contains data only.
- Human-labelled extraction/classification checks are separate from investment-performance scoring.
- Same-period guidance and TTM cash arithmetic are verified independently of Astra.
- Every inspected variant and retry is linked to its hypothesis family and budget.
- Comparisons show cash/exposure differences, uncertainty, temporal dependence and recurring research costs.
- Historical LLM performance is labelled exploratory; prospective observations retain arrival/processing timestamps.

Insufficient coverage or an inconclusive challenger is a completed research result. Do not keep searching until the results look attractive.

## Slice 5 — strategy evidence in Research

User outcome: the new capabilities are usable inside the existing product.

Add `StrategyResearchPanel.tsx`, `StrategyEvidencePanel.tsx`, and typed research API helpers under `apps/web/src/`. Wire into `ResearchWorkspace.tsx` with a symbol/strategy view choice. Keep the existing symbol research and Quant handoff working. Detail panels expose manifests and trial history without forcing internal IDs into the primary flow.

Acceptance: create draft, freeze, queue, watch status, inspect result, revise, and request paper review; refresh retains state. Test error and empty states, keyboard operation and desktop layout. Clear badges distinguish fixture, historical, prospective and broker-paper evidence. Do not add another top-level room.

## Slice 6 — portfolio deployment and execution hardening

User outcome: an approved strategy can propose a bounded set of paper orders through the existing broker boundary.

Add deployment, target, reservation and execution-attempt models/repositories under `tradingagents/research/`. Add a deployment-to-program join table. Extend `ui/brokers/service.py`, `ui/constraints.py`, `ui/brokers/alpaca.py`, `ui/room_policy.py` and relevant APIs narrowly. Add a deployment panel to Quant, preserving existing previews.

Proposed actions: `POST /api/research/deployments`, `POST /api/research/deployments/{id}/review`, and explicit `/activate`, `/pause`, `/resume`, `/retire`. Backend transition handlers enforce authority, evidence references and paper capability. A request cannot freely assign its own state.

Required fixes before activation:

- Replace synthetic constraint context with fresh broker/account snapshots for deployments; fail closed on missing account facts.
- Check constraints and approval against the exact final quantity immediately before submission.
- Reject bracket budgets below a valid share rather than rounding up to one share.
- Enforce final total exposure after sizing methods and every execution leg.
- Reserve cash and pending exposure transactionally across deployments/manual orders.
- Persist and claim attempts before broker submission; reconcile unknown outcomes by client order ID before retrying.
- Give reductions/exits explicit treatment under pause/drawdown rules; pause never means silent liquidation.

Acceptance scenarios: stale account, revoked approval, capital change between preview and submit, two competing strategies, duplicate triggers, sub-share budget, lost response after accepted order, partial fill, crash/restart, cancellation not acknowledged, and holdings changed outside TradeMaster. For ambiguous submission, the verified outcome is at most one economic order, not merely one HTTP attempt.

Keep per-order human approval for this release. No strategy-level unattended authority or live broker path is added.

## Slice 7 — accounting and prospective validation

User outcome: Performance explains what happened with reconciled numbers and links every result to a strategy version.

Add cash-flow, position/fill attribution and equity snapshot persistence plus a reconciliation worker. Extend `PerformanceWorkspace.tsx` to read real history. Record theoretical targets, approved targets and actual fills separately so human delay and rejection are visible.

Acceptance:

- Broker account cash/positions and internal records reconcile with explicit discrepancies.
- Deposits and withdrawals do not inflate strategy return.
- Splits/dividends, realized/unrealized P&L, fees, cash yield and manual trades reconcile to small hand-calculated cases.
- Startup/reconnect identifies unknown submissions before new entries.
- Operator pauses a deployment, sees outstanding orders/positions, and resumes only after current review.
- Paper fills and conservative analytical cost adjustments remain visibly separate.
- A fixture replay is automated; an actual provider-backed paper smoke is recorded separately and requires configured credentials and the existing human order approval.

## Release acceptance walkthrough

1. Save the trend hypothesis and freeze its plan, version and snapshot.
2. Run it and its control; inspect costs, equity, missing inputs and the complete trial list.
3. Run the guidance-quality three-arm comparison on labelled fixtures, then eligible genuine data when available.
4. Verify a negative or inconclusive result stays negative/inconclusive and cannot self-promote.
5. Request paper review of an eligible version with explicit account, funding envelope and policy.
6. Approve and submit one permitted paper order; observe the broker acknowledgement and reconciled fill.
7. Restart between accepted submission and local acknowledgement; confirm no duplicate economic order.
8. Inspect persisted equity and attribution, pause, and propose a new strategy version without mutating the active one.

Report three statuses separately: software acceptance, research evidence, and broker-paper readiness. No performance claim or live-trading completion follows from passing this walkthrough.

## Verification scope and open decisions

Each slice runs focused tests for the contracts it changes, plus existing regression suites for touched paths. Broker work requires meaningful failure/recovery tests. UI work requires a production build and browser verification of the changed user flow. Documentation-only design work does not require executing the application test suite.

Remaining decisions are recorded rather than silently inferred: actual provider coverage and entitlements; LEAN adapter spike outcome; exact experiment dates/universe; data/compute budget; calibrated evidence thresholds; paper account; capital limits and investor withdrawal/drawdown preferences. The first two slices can proceed without those account-specific inputs.

Later features: unattended strategy mandates, live execution, shorts, options/futures, multi-currency accounting, tax-aware allocation and withdrawal planning. Each depends on additional instrument/account evidence and explicit product scope.
