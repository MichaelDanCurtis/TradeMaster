# TradeMaster Big Feature Play

This document describes the implementation-oriented architecture for the main TradeMaster product loop: portfolio review becomes research, research becomes a broker-reviewable thesis, the brokerage floor turns approved theses into execution programs, operations allocates funding and policy, trigger services monitor paper algorithms, and historical outcomes improve future reviews.

## Implemented Room Model

TradeMaster is now organized around seven durable product rooms. The rooms are authority boundaries as much as navigation:

1. **Briefing Room** - morning and meeting surface for recommendations, portfolio posture, liabilities, exceptions, scheduled reports, and operator decisions.
2. **Current Portfolio** - provider-backed account, holdings, cash, mandate split, allocation posture, and missing-fact review before any allocation can become actionable.
3. **Research Office** - TradingAgents runs, imported financial-services research packs, deep research, advisory reports, and research-to-brokerage trade thesis drafts.
4. **Brokerage Floor** - market charts, paper execution algorithm previews, trade thesis review, Webull handoff support, trigger monitoring, and paper program oversight.
5. **Operations & Private Office** - funding allocation review, source-of-funds checks, liability/tax/compliance tracks, goals, assets, dossiers, and approval-ledger decisions.
6. **Agent Builder** - custom agent definition, workflow composition, provider-role review, and promotion into destination-room grants.
7. **Settings** - provider readiness, secret references, LLM/model routing, backup status, schedules, traces, and administrative controls.

Every room shares the same operator decision vocabulary: accept, reject, revise, defer, and escalate. Room policy grants decide which tools a room can use; moving an artifact to a different room does not carry hidden authority with it.

## Product Spine

TradeMaster should feel like a private office with specialized rooms, not one agent with too much authority. Each room owns a different decision boundary.

1. **Briefing Room portfolio review**
   - Ingest Plaid read-only account context, saved goals, current holdings, cash, exposure, watchlists, historical fills, and active execution programs.
   - Produce a structured `portfolio_review` that identifies opportunities, risks, mandate drift, cash needs, concentration issues, and follow-up research questions.
   - The review can recommend research or operational review, but it cannot create orders.

2. **Current Portfolio readiness review**
   - Keep provider-backed holdings, cash, liabilities, tax lots, broker authority, paper/live mode, and account routing visible.
   - Label missing facts explicitly until Plaid, brokerage, market data, tax, and compliance providers are connected and healthy.
   - Decide which positions belong in the human-managed Webull lane, the Alpaca paper harness, or the watch-only/research queue. Current Portfolio can recommend next rooms, but it cannot stage trades.

3. **Research Office stock research**
   - Research agents investigate symbols, sectors, earnings, filings, news, valuation, macro context, and prior internal notes.
   - Their durable output is a `trade_thesis`, not an order. It includes symbol, direction, horizon, conviction, catalysts, invalidation conditions, risk notes, source reports, suggested timing, and links back to the originating portfolio review.
   - Research agents can ask for more data, reject weak ideas, or promote a thesis to broker review.

4. **Brokerage Floor handoff**
   - Broker/execution agents receive `trade_thesis` records and decide whether to reject, request more research, generate a human Webull handoff, or create a gated execution intent.
   - For automated paths, the brokerage floor chooses an approved algorithm template such as bracket order, trailing stop, DCA ladder, staged accumulation, rebalance, hedge, tax-loss harvest, or custom quant strategy.
   - The broker layer creates an `execution_program`, but the program is not armed until allocation, compliance, constraints, and required human approvals pass.

5. **Operations funding and private-office review**
   - Private-office, risk, tax, goals, and compliance agents review capital source, mandate fit, account isolation, drawdown rules, concentration, liquidity, tax concerns, and user goals.
   - Their durable output is a `funding_allocation_review` and one or more `approval_ledger_entry` records.
   - Operations agents can approve, deny, cap, defer, or require human confirmation. They do not design research conclusions and do not submit broker orders.

6. **Execution program monitor**
   - Armed execution programs run as durable state machines. They own algorithm parameters, capital envelope, current state, open orders, stop rules, pause rules, kill conditions, and audit history.
   - Deterministic trigger rules emit `trigger_event` records from market data, schedule events, news/sentiment signals, order fills, drawdowns, rejected orders, cash changes, mandate drift, and circuit breakers.
   - Trigger events can wake broker, risk, research, tax, goals, or human approval workflows. Triggers never directly submit orders.

7. **Historical feedback**
   - Completed, paused, killed, rejected, and manually executed ideas feed back into future portfolio reviews.
   - Performance attribution links `portfolio_review` -> `trade_thesis` -> `funding_allocation_review` -> `execution_program` -> `trigger_event` -> `approval_ledger_entry`.
   - Quant and research agents use this history to compare thesis quality, algorithm suitability, risk-rule effectiveness, and manual Webull outcomes.

## Canonical Product Flow

The intended current flow is:

`portfolio_review` -> `trade_thesis` -> `execution_program` draft -> `funding_allocation_review` -> approved paper allocation -> monitored paper algorithm -> outcome feedback.

In room terms:

1. Briefing Room and Current Portfolio create a provider-aware portfolio review with missing facts called out.
2. Research Office turns the accepted research question into an advisory thesis.
3. Brokerage Floor turns an accepted thesis into a paper-only execution program preview.
4. Operations & Private Office reviews funding source, liquidity, mandate fit, tax, compliance, and provider gaps.
5. Human approval and deterministic policy checks are required before the paper program is armed.
6. The trigger service monitors the paper program and wakes the right room when time, price, volume, sentiment, report, risk, or compliance rules fire.
7. Outcomes, killed programs, deferred theses, manual Webull notes, and approval decisions feed the next portfolio review.

No live trading path is part of this flow. Live broker submission requires a future explicit tool grant, provider approval, symbolic veto coverage, paper proving evidence, and human approval.

## Agent Boundaries

TradeMaster uses two trading-authority agent classes: research and execution. Private-office, compliance, tax, and goals agents are review/control teams around those classes; they can approve, deny, cap, defer, or escalate, but they are not a third class of trading agent.

### Research Agents

Research agents produce analysis artifacts only. They can create portfolio questions, stock research reports, watchlist updates, and `trade_thesis` records. They cannot create broker orders, arm execution programs, modify funding mandates, bypass approval gates, or call broker APIs.

### Execution Agents

Execution agents operate inside the brokerage floor. They can translate approved theses into execution intents, choose approved algorithm templates, create `execution_program` records, evaluate trigger events, and request approvals. They cannot bypass symbolic constraints, private-office allocation decisions, paper-mode requirements, or human approval gates.

### Private-Office And Compliance Reviewers

Private-office reviewers own funding, policy, goals, tax, compliance, and audit review. They create `funding_allocation_review` and `approval_ledger_entry` records. They can approve, deny, cap, pause, or escalate programs, but they do not write investment research or directly operate broker APIs.

## Operational Agent Regression Contract

The operational-agent spine is a product contract, not just implementation detail:

- **Activation surfaces** are visible and bounded. Agents activates runnable research and execution roles; Agent Builder opens framework/planned roles for design, editing, and manifest review.
- **Research agents** stay advisory. They can run research, draft reports, produce trade theses, and hand work to brokerage review, but they cannot create broker orders, arm execution programs, or bypass approvals.
- **Execution agents** stay approval-gated. They can preview paper execution, evaluate trigger wakeups, select approved algorithms, create execution-program drafts, and request approvals, but they cannot bypass provider readiness, symbolic vetoes, funding decisions, paper-mode requirements, or human approval.
- **Approvals** are represented in shared room actions, approval ledger entries, execution-program events, and the Agent Builder approval gate. A saved workflow, trigger, or provider assignment does not grant live broker authority.
- **Trigger wakeups** are deterministic events that route time, price, volume, sentiment, report, risk, and compliance changes to the right room, target agent, workflow, or approval path. Trigger records wake work; they never submit orders.
- **Provider readiness** must travel with the reviewed artifact. Research workflows need LLM, market data, observability, and safety facts. Execution workflows also need broker paper-account and portfolio facts before arming.
- **Agent Builder** captures workflow composition: agent nodes, data nodes, tool nodes, control nodes, provider-role requirements, LangGraph/LangChain runtime choice, scheduler controls, PyReason gates, Alpaca adapters, and human approval gates.

## Provider Readiness

Provider readiness is an explicit product state, not a background configuration detail.

- **Settings** owns provider configuration, secret references, model/provider routing, snapshot/backup status, trace status, and readiness checks.
- **Current Portfolio** owns whether provider facts are present enough to support allocation discussion: holdings, cash, liabilities, tax lots, paper/live routing, broker permissions, and mandate mapping.
- **Research Office** can run with market data and LLM providers, but its output remains advisory when account, tax, broker, or compliance facts are missing.
- **Brokerage Floor** requires paper broker capability, market data freshness, room-policy approval, and algorithm-specific provider facts before a paper program can be armed.
- **Operations & Private Office** requires banking, brokerage, tax, liability, and compliance facts before funding allocation can be approved.

Readiness gaps must stay visible in the artifact being reviewed. A missing provider fact blocks escalation to broker execution; it should never be silently filled with assumptions.

## Core Data Objects

### `portfolio_review`

Snapshot-level assessment of accounts, holdings, goals, risk, liquidity, active programs, pending theses, and follow-up research needs.

Key fields: `id`, `created_at`, `account_snapshot_ids`, `goal_ids`, `holding_summary`, `cash_summary`, `risk_findings`, `opportunity_candidates`, `active_execution_program_ids`, `recommended_research_requests`, `ledger_entry_ids`.

### `trade_thesis`

Research Office artifact that can be reviewed by broker agents or used for human Webull trading.

Key fields: `id`, `portfolio_review_id`, `symbol`, `direction`, `time_horizon`, `conviction`, `catalysts`, `invalidation_conditions`, `risk_notes`, `source_report_ids`, `suggested_timing`, `status`, `broker_review_notes`.

### `funding_allocation_review`

Operations decision record for whether a thesis or execution program may use capital.

Key fields: `id`, `trade_thesis_id`, `execution_program_id`, `mandate_id`, `account_id`, `capital_envelope`, `max_loss`, `drawdown_limit`, `concentration_result`, `tax_notes`, `compliance_verdict`, `approval_requirement`, `decision`.

### `execution_program`

Durable state machine for a broker-managed plan.

Key fields: `id`, `trade_thesis_id`, `algorithm_template_id`, `algorithm_version`, `mode`, `state`, `account_id`, `mandate_id`, `capital_allocation`, `risk_constraints`, `open_order_refs`, `stop_rules`, `pause_rules`, `kill_rules`, `trigger_rule_ids`, `approval_ledger_entry_ids`.

### `trigger_event`

Deterministic event that wakes the right workflow with context.

Key fields: `id`, `execution_program_id`, `trigger_rule_id`, `event_type`, `source_signal_ids`, `market_data_snapshot`, `program_state_snapshot`, `constraint_verdict`, `created_at`, `routed_to`, `resulting_action`.

### `approval_ledger_entry`

Append-only audit record for material decisions and state transitions.

Key fields: `id`, `created_at`, `actor_type`, `actor_id`, `object_type`, `object_id`, `action`, `reason`, `inputs_hash`, `constraint_verdict`, `human_required`, `human_actor_id`, `decision`, `previous_state`, `next_state`.

## Safety Boundaries

- Research agents cannot trade. Their highest-authority trading artifact is a `trade_thesis`.
- Execution is paper-mode and approval-gated by default. AI-managed live execution is out of scope until the high-risk harness is proven separately.
- Plaid is read-only forever. It can provide banking, account, holdings, securities, balance, and transaction context, but no money movement or trade submission.
- Webull remains human-managed. TradeMaster can produce Webull handoff cards, track manual status, and record user-entered fills or rejections, but should not automate Webull execution.
- Alpaca starts as agent-facing market data and later paper broker execution. The Alpaca high-risk AI harness is a later, isolated path with explicit funding limits, paper proving, symbolic vetoes, monitoring, and kill switch.
- Trigger events do not submit orders. They wake workflows that still pass through execution, allocation, constraints, and approval gates.
- Symbolic constraints are deterministic veto points for concentration, drawdown, daily turnover, PDT, wash-sale lookahead, account mandate, cash, and circuit-breaker rules.
- The ledger is the business truth. LangGraph checkpoints, LangFuse traces, broker refs, and provider events link back to ledger entries, not the other way around.

## Near-Term Implementation Order

This order follows the existing roadmap slices and keeps each code increment shippable.

1. **Expose persistence and provider setup in the UI**
   - Surface provider configs, secret refs, health, snapshot status, and local API connectivity.
   - Keep Alpaca as market-data capable, Plaid as read-only, and Webull as human-managed.

2. **Wire real TradingAgents runs**
   - Replace fake run events with `TradingAgentsGraph.propagate()` while preserving the normalized run-event contract.
   - Correlate TradeMaster run ids with LangGraph checkpoints and future LangFuse traces.

3. **Add Alpaca market data**
   - Implement the market data provider protocol and use Alpaca bars, quotes, and streams where available.
   - Do not require live broker credentials.

4. **Add Plaid read-only portfolio snapshots**
   - Ingest accounts, balances, holdings, securities, and transactions.
   - Create normalized snapshots that the Briefing Room can consume.

5. **Create portfolio review records**
   - Persist `portfolio_review` output from Briefing Room runs.
   - Link reviews to account snapshots, goals, active execution programs, and research requests.

6. **Build trade thesis handoff**
   - Persist `trade_thesis` records from research agents.
   - Add broker-review states: rejected, needs research, Webull handoff, execution intent candidate.
   - Ledger every research-to-broker handoff.

7. **Build funding allocation review**
   - Add `funding_allocation_review` and `approval_ledger_entry` records.
   - Wire deterministic symbolic checks before any program can be armed.

8. **Build execution programs**
   - Persist `execution_program` state machines with algorithm template, capital allocation, state, stop rules, pause rules, and audit history.
   - Require paper mode and human approval for initial arming.

9. **Add trigger harness and simulations**
   - Add deterministic trigger rules and `trigger_event` records.
   - Test trigger simulations before connecting live market streams or scanners.

10. **Add perception scanner and feedback loop**
    - Add low-cost scheduled scans for watchlists and active execution programs.
    - Feed completed program outcomes, manual Webull outcomes, and rejected theses into future portfolio reviews.

11. **Add Webull handoff workflow**
    - Generate handoff cards from `trade_thesis` records.
    - Let the user track manual status, fills, rejections, and notes.

12. **Defer high-risk Alpaca AI harness**
    - Only start after paper programs, symbolic constraints, trigger monitoring, provider observability, and approval ledgers are stable.

## First Thin Vertical Slice

The first compelling end-to-end slice should avoid live trading:

1. Briefing Room creates a `portfolio_review` from saved/mock portfolio context.
2. Research Office creates a `trade_thesis` for one symbol.
3. Brokerage Floor converts it into a paper-only `execution_program` draft.
4. Operations creates a `funding_allocation_review` and required `approval_ledger_entry`.
5. User approval arms the paper program.
6. Simulated `trigger_event` records move the program through paused, adjusted, completed, or killed states.
7. The next `portfolio_review` includes the program outcome as historical feedback.

That slice proves the architecture without Plaid money movement, Webull automation, or live Alpaca trading.
