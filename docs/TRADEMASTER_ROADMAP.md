# TradeMaster Roadmap

## 2026-09-07: New SPY outperformance research program

The [SPY outperformance research roadmap](SPY_OUTPERFORMANCE_RESEARCH_ROADMAP.md)
sets the next research priorities: original filing changes, cash redeployment
through institutional holdings, and corporate-action opportunities with explicit
small-holder or realization terms. Customer–supplier propagation and a combined
event model follow only if their data and simpler baselines qualify.

The target comparison is whole-account net wealth over rolling three-year
periods, with shorter and longer diagnostics, explicit costs, capacity and risk.
The [first data pilot](EVENT_RESEARCH_PILOT.md) now captures and compares 100
original filing pairs, with versioned identity checks and initial event/holdings
audits. The follow-on historical filing test now has a qualified terminal-wealth
comparison; historical universe and control-accounting limitations remain. The user has set a **$0 incremental
data subscription budget**. Follow the [public-data execution plan](RESEARCH_WITHOUT_NEW_DATA_SPEND.md), starting with a separately registered historical S&P equal-weight filing experiment. This work preserves the retirement
below and the separately frozen forward/paper studies.

The [historical filing experiment](HISTORICAL_FILING_STUDY.md) now has a frozen
ten-decision specification and completed 7,542-document capture. Its selected
portfolio returned 21.38% annualized versus SPY's 22.86% at 11 bps per side over
April 2019–September 2021. It did not meet the SPY objective. The matched eligible
control is incomplete; one trading-halt day also limits daily risk statistics.
The [free ownership-data pilot](PUBLIC_OWNERSHIP_DATA_PILOT.md) completed source
checks on a 2.3-million-row archive. Its [three-event cash-flow follow-on](CASH_FLOW_PILOT.md)
also completed, below SPY and matched controls. Preserve these negative results;
neither prototype qualifies for deployment or tuning on the same outcomes.

## 2026-09-07: Insider and quality strategy retired

The user approved retiring the fixed insider-purchase + annual financial-quality
+ risk-controls strategy after its final historical test failed. It is closed
for further tuning and deployment promotion. Remove it from follow-on work;
adding news or another filter is not an automatic continuation of this hypothesis.

The [retirement decision](research-decisions/insider-quality-final-retirement.json)
records the scope and hashes of the preserved evidence. See the
[final test](INSIDER_QUALITY_FINAL_TEST.md) for results and reproducibility.
Research tooling remains available for reviewing that evidence. This decision
does not select a replacement strategy or change other existing trials.

## 2026-09-04: Executable research direction

The next product increment is a personal quant research workflow: Astra develops and challenges hypotheses; deterministic evaluation produces evidence; reviewed strategy versions feed the existing paper execution surface. Start with a diversified trend baseline and a guidance/cash-quality challenger. This direction extends the existing rooms and authority boundaries.

See [Quant research design](QUANT_RESEARCH_DESIGN.md) for the repository assessment, strategy specifications and architecture, and [Build sequence](QUANT_RESEARCH_BUILD_PLAN.md) for implementation slices and acceptance criteria. These are design artifacts; the research engine and new deployment lifecycle are not yet implemented. The earlier roadmap below remains historical context and existing work to preserve.

This is the working build order for TradeMaster after the v1.2 local persistence foundation. The product direction is a personal private-office platform with four control surfaces:

- Webull-centered human-managed trading with AI research and strategy support.
- Alpaca/Plaid/provider-backed agent research and account context.
- A separate AI-managed high-risk portfolio harness with isolated funding, paper proving, symbolic vetoes, monitoring, and a kill switch.
- Imported financial-services research/body-of-work agents that can create trade theses, wealth briefs, tax questions, portfolio reviews, and research artifacts without owning broker authority.

## Current Architecture Snapshot

The implemented product spine is room-based:

- **Briefing Room**: morning/private-office brief, recommendations, report schedules, exception review, and shared decision actions.
- **Current Portfolio**: provider-backed holdings, cash, mandate split, allocation posture, missing-provider-fact review, and handoff routing.
- **Research Office**: advisory TradingAgents reports, imported research packs, thesis drafting, and research-to-brokerage handoffs.
- **Brokerage Floor**: market view, thesis review, Webull handoff support, paper execution algorithm previews, and trigger monitoring.
- **Operations & Private Office**: funding allocation review, liability/tax/compliance tracks, goals, assets, dossiers, and approval ledger.
- **Agent Builder**: custom agent definitions, workflow composition, provider-role review, and saved manifests.
- **Settings**: provider readiness, LLM/model routing, secret refs, backups, traces, schedules, and administrative controls.

The trading authority model has two agent classes:

- **Research agents** can produce portfolio reviews, research reports, watchlist updates, and advisory trade theses. They cannot stage orders, arm execution programs, call broker APIs, or bypass approvals.
- **Execution agents** can convert approved theses into paper execution program previews, evaluate trigger events, choose approved algorithms, and request approvals. They cannot bypass provider readiness, symbolic vetoes, private-office funding decisions, paper-mode requirements, or human approval gates.

Private-office, compliance, tax, goals, and risk teams are control/review surfaces around those two classes. They can approve, deny, cap, defer, pause, or escalate, but they do not become hidden trading agents.

The canonical product loop is:

`portfolio_review` -> `trade_thesis` -> paper `execution_program` draft -> `funding_allocation_review` -> approved funding allocation -> monitored paper algorithm -> outcome feedback.

The trigger service is the wakeup layer for execution programs and scheduled perception. Time, price, volume, sentiment, report, risk, and compliance triggers can wake the right room or approval workflow, but triggers do not directly submit orders. No live trading path is active without future explicit approvals, provider capability, symbolic veto coverage, paper proving, and a separate live tool grant.

## Operational Agent Regression Contract

Wave 3 operational-agent coverage must keep the usable activation surfaces explicit:

- **Agents** is the live activation surface. Active research agents expose research runs; active execution agents expose paper execution previews. Framework and planned agents route to Agent Builder instead of pretending to run.
- **Research agents** and **Execution agents** are the only trading-authority classes. Research agents produce advisory artifacts and trade theses. Execution agents can create paper previews, evaluate trigger wakeups, and request approvals, but they remain blocked by provider readiness, symbolic constraints, paper mode, and human approval.
- **Approvals** remain visible in room policies, approval-ledger actions, execution-program events, and the human approval gate node. No trigger, builder draft, or provider change grants hidden broker authority.
- **Trigger wakeups** are deterministic routing records for schedules, price, volume, sentiment, report, risk, and compliance events. They wake the appropriate room, target agent, workflow, or approval path; they do not submit orders.
- **Provider readiness** is part of the agent contract. Research readiness needs LLM, market data, observability, and safety facts; execution readiness additionally needs broker paper-account and portfolio facts before a program can be armed.
- **Agent Builder** is the workflow design and review surface. Builder workflows can compose research and execution nodes, provider roles, LangGraph/LangChain runtimes, scheduler controls, PyReason gates, Alpaca adapters, and approval gates, but saved manifests remain drafts until routed through room policy.

## 1. Surface The Persistence Foundation In The UI

Make the new durable backend visible from the web app.

- Settings reads `/api/provider-configs`, not only static frontend provider data.
- Settings shows Alpaca as agent-facing market/trade data, Webull as human-managed cockpit, and Plaid as read-only banking/account aggregation.
- Settings can save `secret_ref` values without accepting raw API keys.
- Settings can create a local snapshot manifest and show the result.
- The UI remains useful when the FastAPI backend is offline.

## 2. Run Both Local Servers As One Dev Experience

Make the MacBook server experience boring.

- Add a documented command or script that starts FastAPI and Next together.
- Make Next API proxy or environment defaults point at the local FastAPI server.
- Add health indicators for web, API, DB, provider registry, and snapshot path.
- Make server restart predictable after code changes.

## 3. Wire Real TradingAgents Runs

Replace fake run events with real `TradingAgentsGraph.propagate()` execution.

- Preserve the existing normalized event contract.
- Emit LangGraph node progress into `RunEvent`.
- Correlate TradeMaster run ids with LangGraph checkpoint ids and future LangFuse trace ids.
- Keep fake mode available for tests and demos.

## 4. Add Alpaca Market Data For Agents

Use Alpaca first for real agent-facing market/trade data.

- Implement `MarketDataProvider` protocol.
- Add Alpaca historical bars, minute bars, quotes, and trade stream where available.
- Keep Webull as the human trading cockpit/handoff surface.
- Do not require live broker credentials.

## 5. Add Provider Secret Setup Flow

Make credential setup safe.

- Store only `secret_ref` in SQLite.
- Use macOS Keychain on the MacBook server.
- Add provider health checks that can verify whether a secret exists without revealing it.
- Add audit events for secret access and provider health checks.

## 6. Add Plaid Read-Only Banking And Account Aggregation

Make Pillars 1 and 2 real.

- Add Plaid Link flow.
- Ingest balances, accounts, holdings, securities, and transactions.
- Create normalized portfolio snapshots.
- Preserve the rule that Plaid is read-only forever.

## 7. Build Goals And Assets Workspace

Turn goals and asset dossiers into editable durable records.

- Create/edit goals such as yacht, college fund, real estate, liquidity, and business capital.
- Create/edit asset dossiers for houses, cars, boats, firearms, equipment, accounts, and documents.
- Link goals/assets/accounts/advisor notes through entity edges.
- Allow agents to suggest changes, but require approval for material changes.

## 8. Build The Symbolic Constraint Engine

Put deterministic rules between agents and broker execution.

- Position concentration caps.
- Sector concentration caps.
- Drawdown circuit breakers.
- Daily turnover limits.
- PDT checks.
- Wash-sale lookahead.
- Account-aware rule checks.
- Hard veto on any breached rule.

## 9. Build Portfolio Mandate Management

Make human-managed and AI-managed high-risk portfolios explicit in the UI.

- Human-managed Webull strategy mandate.
- AI-managed high-risk mandate with paper proving.
- Funding limits and account isolation.
- Kill switch, drawdown cap, turnover cap, position cap.
- Ledger-visible mandate changes.

## 10. Add Alpaca Paper Broker Adapter

Enable real paper trades behind approvals.

- Official Alpaca SDK.
- Paper mode only by default.
- Intent -> preview -> approve -> submit flow.
- Symbolic engine veto before submission.
- Full audit trail.

## 11. Add LangFuse Observability

Make agent behavior inspectable.

- Correlate TradeMaster runs, LangGraph checkpoints, and LangFuse traces.
- Record model/provider/cost metadata.
- Preserve TradeMaster ledger as the business truth.

## 12. Add Encrypted Offsite Backup

Make the MacBook server durable.

- Done: snapshot SQLite with a manifest and SHA-256 hashes.
- Done: create encrypted local `.tmbackup` artifacts from server-side secret references.
- Done: add restore verification that decrypts the artifact and verifies file hashes.
- Next: add selected document metadata once the document vault exists.
- Next: push encrypted artifacts to an offsite target.

## 13. Add Scheduled Agents

Move from on-demand reports to recurring operations.

- Morning private-office digest.
- Market-hours agent watchers.
- Plaid daily snapshot review.
- Weekly goals review.
- Quarterly tax/wealth review brief.
- Hourly low-cost perception scans for news, filings, social, and watchlist changes.
- Run schedules target symbols, sectors, accounts, goals, assets, document sets, and execution programs.

## 14. Import Financial-Services Research Agent Packs

Bring in Anthropic's financial-services repository as portable research content, not as a Claude-only runtime.

- Import agent prompts, skills, commands, MCP connector declarations, managed-agent cookbooks, subagent topology, steering examples, output schemas, and guardrails.
- Normalize imported agents into TradeMaster agent-pack records.
- Keep Claude Managed Agents optional; route execution through TradeMaster provider roles.
- Support Anthropic, OpenAI, LM Studio, OpenRouter/Mistral, and future OpenAI-compatible providers where capabilities fit.
- Start with Market Researcher, Earnings Reviewer, and Wealth Management skills.
- Surface imported agents in Agents, Deep Research, Agent Builder, and scheduled morning briefs.
- Keep imported financial-services agents research/advisory only; no broker tools.

## 15. Build Trade Thesis Handoff

Turn research output into broker-reviewable trade theses.

- Research agents produce structured trade theses, not orders.
- A trade thesis includes symbol, direction, horizon, conviction, catalysts, invalidation conditions, source reports, risk notes, and suggested timing.
- Broker agents review theses and decide whether to reject, ask for more research, create a Webull handoff, or create an execution intent.
- Execution intents are separate from research theses and include target action, mandate, account, capital envelope, risk constraints, and approval needs.
- Every handoff from research to broker review is logged in the private-office ledger.
- Human-managed Webull trades can consume the same thesis object without entering the AI-managed harness.

## 16. Build Execution Programs

Represent broker-agent plans as durable, stateful execution programs.

- An execution program owns the selected algorithm, current state, capital allocation, open orders, stop rules, pause rules, and audit history.
- Broker agents choose algorithms such as bracket order, trailing stop, DCA ladder, staged accumulation, rebalance, hedge, tax-loss harvest, or custom quant strategy.
- Execution programs persist state across server restarts.
- Execution programs emit lifecycle events: created, armed, paused, resumed, adjusted, completed, failed, killed.
- The symbolic constraint engine evaluates every state transition.
- Paper mode is required by default for AI-managed programs.
- Human approval is required when a program is first armed and when policy requires escalation.

## 17. Build Trigger Harness

Wake agents only when deterministic trigger rules say they need to think.

- Trigger conditions include date/time, market open/close, stock price, price gap, volume spike, VWAP deviation, volatility, drawdown, order fill, order rejection, news signal, sentiment signal, filing event, earnings window, portfolio exposure, cash balance, mandate drift, and circuit-breaker state.
- Trigger evaluation is deterministic and ledgered.
- Trigger rules can wake a broker agent, research manager, risk manager, goals agent, tax agent, or human approval workflow.
- Triggers do not directly submit broker orders.
- Trigger events carry full execution-program state, recent market data, source signal IDs, and current constraint verdicts.
- Add trigger simulation tests before connecting live market streams.

## 18. Add Hourly Perception And Sentiment Scanner

Use cheap scheduled perception jobs as market sensors.

- Run hourly scans for watchlist symbols and active execution programs.
- Pull headlines, filings, social summaries, source metadata, and ticker/entity extraction.
- Cluster duplicate stories before spending LLM tokens.
- Classify sentiment, severity, catalyst type, affected symbols, source count, and confidence.
- Write structured signals to the ledger.
- Deterministic trigger rules evaluate those signals.
- Escalate to a stronger model or full-article read only when severity and confidence cross thresholds.
- Wake broker or research agents only after thresholded, auditable signal confirmation.

## 19. Build Quant Trader And Algorithm Library

Create a controlled place for algorithm design without giving research agents broker authority.

- Quant trader agents design, compare, backtest, and improve execution algorithms.
- Algorithms are versioned, parameterized, and stored as approved strategy templates.
- Broker agents select from approved templates based on thesis, mandate, liquidity, volatility, time horizon, and risk rules.
- Custom algorithms start in simulation, then paper mode, then explicitly approved live-preview mode.
- Algorithm performance feeds the historicals/feedback loop.
- Quant agents cannot bypass approval gates, symbolic constraints, or mandate funding limits.

## 20. Build Webull Handoff Workflow

Support human-managed trading workflow.

- Generate handoff cards for Webull.
- Track manual execution status.
- Let the user record fills or rejected ideas.
- Keep Webull automation separate from the high-risk AI harness.
- Link Webull handoffs back to the originating trade thesis and research reports.

## 21. Add High-Risk AI Harness

Only after paper proving, symbolic constraints, provider instrumentation, execution programs, and trigger monitoring are stable.

- Dedicated paper account first.
- Separate high-risk funding mandate.
- Continuous monitoring.
- Hard kill switch.
- Daily summary and exception alerts.
- Execution programs run inside the harness; agents wake on trigger events rather than staying continuously active.
- Live funds only after explicit configuration.

## 22. Add Tax And Attorney Briefing Layer

Make Pillar 2 attorney-friendly.

- Output questions and option trees, not advice-shaped recommendations.
- Cite rules, jurisdictions, effective dates, and data anchors.
- Generate Markdown/PDF briefs for attorney triage.
- Track attorney/bookkeeper feedback as durable records.
- Tax agents review active/past execution programs, Webull handoffs, realized/unrealized gains, wash-sale risk, asset ownership structures, and goal funding paths.

## 23. Add Document Vault

Store and reason over paperwork safely.

- Metadata first.
- Encrypted attachments later.
- Source, date, confidence, advisor, and renewal fields.
- Link documents to assets, goals, providers, and tax issues.

## 24. Add Retrieval Layer

Add local retrieval before pgvector.

- SQLite FTS and/or sqlite-vec for local retrieval.
- Embed reports, advisor notes, tax memos, and documents.
- Keep relational records as truth.
- Migrate to Postgres + pgvector when scale or deployment needs justify it.

## 25. Add Mobile/Mac Clients

After the local API is stable.

- iOS app for approvals, alerts, digests, and goal review.
- macOS app for local server control and notifications.
- Remote clients call the TradeMaster API; they do not read Keychain directly.

## 26. Add Galvo/Coalesce Integration

When ready.

- Route LLM calls through Galvo/Coalesce.
- Keep LangGraph as the current workflow runtime until Galvo is production-ready.
- Preserve LangFuse observability and TradeMaster business ledger.

## 27. Room-Based Operating System Pass

Turn the product into a single-person brokerage/private-office operating system instead of a pile of tabs.

- Done: top-level navigation is now Briefing Room, Current Portfolio, Research Office, Brokerage Floor, Operations & Private Office, Agent Builder, and Settings.
- Done: rooms have explicit tool grants, shared decision actions, and policies.
- Done: backend room-policy catalog mirrors the frontend policy model.
- Done: research rooms cannot call broker paper-preview tools.
- Done: execution-algorithm preview and trade preview carry room identity for policy checks.
- Done: generic approval-ledger records capture accept, reject, revise, defer, and escalate decisions for any room entity.
- Done: agent triggers are modeled separately from report schedules and can target time, price, volume, sentiment, report, risk, and compliance events.
- Done: the web client can list/evaluate room policies, record approval ledger entries, and create/list agent triggers.
- Done: room readiness panels map the 15-step plan into room-owned work queues.
- Done: Research Office shows advisory trade thesis handoffs that are not orders.
- Done: Briefing Room recommendation controls now write live accept, reject, revise, defer, and escalate decisions to `/api/approval-ledger`.
- Done: watchlist add/remove flows normalize symbols, persist locally, and send clean quote-refresh inputs.
- Done: Research Office report readers label final and individual agent reports as advisory research, not broker orders.
- Done: Brokerage Floor surfaces active wake-trigger monitoring for time, price, volume, sentiment, news/report, risk, and compliance conditions without live trade submission.
- Done: Agent Builder has a select/edit/save flow for existing agent definitions and preserves edited agent ids in saved manifests.
- Done: backend and web client now expose persisted `/api/trade-theses` advisory handoff records from Research Office to Brokerage Floor.
- Done: Research and Brokerage thesis panels now read live `/api/trade-theses` records instead of seeded handoff cards.
- Done: Research Office can draft advisory thesis handoffs into `/api/trade-theses` without creating an order.
- Done: enabled report schedules create linked scheduled-perception wake triggers.
- Done: paper execution algorithm previews arm linked `risk_threshold` triggers for the execution harness.
- Done: Current Portfolio surfaces account/holding/cash/tax-lot/provider gaps before allocation or brokerage routing.
- Done: portfolio review, order thesis, funding allocation, and execution program panels represent the portfolio review -> research thesis -> execution program -> funding allocation -> monitored paper algorithm flow.
- Done: provider readiness is represented across Settings, Current Portfolio, Research Office, Brokerage Floor, and Operations rather than hidden behind static frontend state.
- Done: Agent Builder edits stay provider-role and room-policy aware; saved workflows do not grant broker authority by themselves.
- Done: execution program templates are paper-only, approval-gated, and monitored by deterministic trigger points.
- Next: enforce room policy in every future tool endpoint, not just broker/algorithm preview.
- Next: add a compliance-gateway review path before any cross-room private-office message can be acted on.
- Next: add canonical backend update endpoints for saved Agent Builder definitions/workflows.
- Next: promote trigger evaluation from preview/readiness state into durable backend lifecycle records for each paper execution program.
- Next: keep live trading unavailable until approval policy, provider permissions, paper proving, and kill-switch controls are deliberately added.
