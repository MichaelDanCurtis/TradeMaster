# TradingAgents UI Design

Date: 2026-04-29
Status: Draft for review

## Summary

TradingAgents already has a useful LangGraph-based trading research engine, but its product surface is an interactive terminal. This design turns it into a local-first trading research terminal with a stable market UI, an agent-driven right rail, report history, and approval-gated Alpaca paper trading.

The first version does not build a general workflow builder. It wraps the existing TradingAgents methodology in a serious interface, proves the product pattern, and leaves custom research-agent composition for v1.5/v2.

## Goals

- Put a polished web interface in front of the existing TradingAgents graph.
- Preserve the current analyst, researcher, trader, risk, and portfolio-manager flow.
- Stream run progress, tool calls, intermediate reports, and final decisions into the UI.
- Show watchlists, price charts, ticker context, saved reports, and decision history.
- Use A2UI/CopilotKit for contextual agent-generated workflow surfaces.
- Add an approval-gated broker abstraction with Alpaca paper trading as the first adapter.
- Keep live trading disabled by default and unreachable without explicit future configuration.

## Non-Goals

- Do not rewrite the TradingAgents engine in v1.
- Do not build a blank-canvas Node-RED-style agent builder in v1.
- Do not enable autonomous trading in v1.
- Do not submit live broker orders in v1.
- Do not let the agent generate the entire application shell.

## Product Shape

The application is a trading terminal plus an agent cockpit.

The stable shell is owned by the app:

- left rail: watchlist, tickers, saved runs, account mode
- center workspace: chart, indicators, quote summary, selected ticker context
- right rail: CopilotKit/A2UI agent surface for run setup, progress, follow-up questions, report review, and trade tickets
- bottom drawer: events, tool calls, token/cost stats, source/data provenance, logs

The agent may generate contextual UI inside approved surfaces, but it does not control global navigation, app layout, authentication, broker mode, or destructive actions.

## V1 User Workflow

1. User opens the app and sees a watchlist with market-style charting.
2. User selects a ticker from the left rail.
3. The center panel shows the ticker chart, quote data, and recent context.
4. The right rail offers a report run setup for the selected ticker.
5. User picks date, analyst set, provider/model, research depth, and checkpoint mode.
6. Backend starts a TradingAgents run and streams graph events to the UI.
7. The right rail progressively renders the current agent state:
   - active analyst or manager
   - tool calls and data source status
   - partial analyst report sections
   - bull/bear debate progress
   - trader proposal
   - risk review
   - final portfolio decision
8. Final report is saved and appears in decision history.
9. If paper trading is enabled, the app creates a paper trade preview from the final decision.
10. User can approve, edit, or reject the paper trade ticket.
11. Approved paper orders are submitted through the Alpaca paper adapter and logged.

## Architecture

### Frontend

Use a React/Next.js app for the operator interface.

Core frontend modules:

- `MarketShell`: fixed app frame, navigation, watchlist, selected ticker state
- `ChartWorkspace`: price chart, indicator overlays, quote snapshot, ticker notes
- `AgentCockpit`: right rail powered by CopilotKit and A2UI-rendered surfaces
- `RunTimeline`: normalized view of LangGraph node progress and tool activity
- `ReportViewer`: analyst sections, debates, final decision, citations, exports
- `DecisionLedger`: saved runs, ratings, outcomes, paper trades, filters
- `TradeTicket`: approval-gated paper order preview and submission flow

The charting layer should use TradingView Lightweight Charts for the first implementation. It is focused on financial time-series UI, avoids hand-rolled canvas logic, and is enough for candlesticks, volume, crosshair inspection, and common overlays.

### Backend

Use a Python API layer next to the existing TradingAgents package.

Core backend modules:

- `runs`: create, stream, cancel, resume, and inspect TradingAgents runs
- `events`: normalize LangGraph chunks into stable UI event types
- `reports`: persist and retrieve saved markdown/json reports
- `market_data`: provide watchlist quotes and chart series
- `brokers`: broker abstraction and Alpaca paper adapter
- `agent_ui`: A2UI message generation and CopilotKit/AG-UI integration
- `settings`: provider/model/API key configuration and feature gates

The backend should wrap the current `TradingAgentsGraph` rather than forking its core behavior. If the existing graph lacks hooks needed for UI streaming, add small event-emission seams around the current stream path.

### A2UI and CopilotKit

CopilotKit provides the React-side agent interaction runtime and a practical bridge for LangGraph-style agent applications. A2UI is used as the declarative UI payload for agent-generated surfaces.

V1 A2UI surfaces:

- run setup confirmation
- active run progress cards
- analyst report cards
- follow-up/narrowing controls
- final report summary
- trade ticket preview
- approval or rejection confirmation

A2UI payloads must be rendered through a constrained component registry. The agent can choose from approved components and bind data into them, but it cannot send arbitrary executable UI code.

### A2A

A2A should be included as an interoperability boundary, not as a reason to overbuild v1. The first useful shape is to expose the TradingAgents research runner as an agent endpoint with an agent card, streaming task lifecycle, and artifacts for reports/trade proposals.

The UI can consume this directly or through CopilotKit/AG-UI where practical. The design should preserve the option to call other A2A-compatible agents later, especially for custom research workflows and the future pharma adaptation.

## Data Model

Key persisted entities:

- `Ticker`: symbol, exchange, display name, metadata
- `Watchlist`: named collection of tickers
- `Run`: ticker, date, config, status, timestamps, selected analysts
- `RunEvent`: run id, node, event type, payload, timestamp
- `Report`: run id, section, markdown, structured metadata
- `Decision`: run id, rating, action, thesis, risk notes, price target, time horizon
- `TradeIntent`: decision id, side, quantity/notional, order type, limits, stop loss
- `BrokerOrder`: trade intent id, broker, environment, status, broker order id
- `Approval`: actor, action, timestamp, before/after payload

Use SQLite for v1 local-first persistence with SQLModel or SQLAlchemy models in the Python backend. The schema should be boring and portable so the app can move to Postgres later without changing product behavior.

## Broker Adapter

Create a broker abstraction from the start.

Interface responsibilities:

- validate environment mode
- fetch account snapshot
- fetch current positions
- estimate order impact
- create order preview
- submit paper order
- read order status
- cancel paper order

V1 concrete adapter:

- `AlpacaPaperBrokerAdapter`

Feature gates:

- `BROKER_MODE=disabled|paper|live_preview`
- default: `disabled`
- live execution is not implemented in v1
- paper order submission requires explicit user approval
- no API key capable of live trading should be used during development

The UI must always display the execution environment. Paper trading should be labeled as paper trading everywhere: account banner, trade ticket, order log, and report history.

## Safety and Approval

The system must distinguish recommendation, intent, and execution.

- Recommendation: TradingAgents final decision and thesis.
- Intent: normalized trade proposal derived from the recommendation.
- Execution: broker adapter submission after approval.

V1 only supports report-only and paper-approved execution. Autonomous mode is a future capability and must not be reachable through hidden flags.

Required safeguards:

- user approval before every broker submission
- immutable approval audit log
- paper/live environment label on every trade surface
- max notional and max position-size checks
- reject unsupported symbols and order types
- no live broker submit method in v1
- clear disclaimers that outputs are research support, not financial advice

## Custom Research Agent Builder Roadmap

The custom builder is deferred intentionally.

V1 proves the interface pattern with the fixed TradingAgents workflow.

V1.5 should add workflow templates and editable presets:

- analyst set presets
- report templates
- data-source bundles
- saved research workflows

V2 should add a visual builder:

- source nodes: market data, filings, transcripts, news, internal docs
- transform nodes: extraction, summarization, scoring, comparison
- reasoning nodes: bull case, bear case, risk review, compliance review
- output nodes: report, trade ticket, citation packet, watchlist update

The builder should compile to a restricted workflow schema that can be translated into LangGraph nodes. It should not generate arbitrary code.

This roadmap is important because the same pattern can later apply to pharma: domain workflow, evidence gathering, agent-generated UI, human approval, and sandboxed execution before consequential actions.

## Testing Strategy

Backend:

- unit tests for event normalization, persistence, and report retrieval
- broker adapter contract tests with fake broker and Alpaca paper mocks
- approval-gate tests proving broker submission cannot happen without approval
- TradingAgents wrapper tests with mocked graph chunks

Frontend:

- component tests for stable shell, run timeline, report viewer, and trade ticket
- A2UI renderer tests for approved component payloads
- end-to-end test for ticker selection through completed report
- end-to-end test for paper trade approval and rejection paths

Integration:

- local smoke test with fake LLM/data events
- optional paper Alpaca smoke test with paper-only credentials
- no test should require live trading credentials

## Implementation Slices

1. App scaffold and local API shell.
2. Run event wrapper around the existing TradingAgents graph.
3. Frontend trading terminal shell with watchlist and chart workspace.
4. Right-rail Agent Cockpit with streamed run progress.
5. Report persistence and decision ledger.
6. A2UI/CopilotKit dynamic surfaces for report and follow-up controls.
7. Broker abstraction with fake broker.
8. Alpaca paper adapter behind approval gates.
9. Paper trade ticket and order history.

## Architecture Decisions

- Ship v1 in this repo as a monorepo-style app, with a frontend app folder and a Python API layer beside the existing package.
- Use TradingView Lightweight Charts for the initial market chart workspace.
- Use SQLite with SQLModel or SQLAlchemy for local-first persistence.
- Build the local run streaming API before the A2A endpoint. A2A should wrap the stable run/task/artifact model after the local event contract is real.
- Replace CLI display-specific logic with normalized run events. Reuse existing TradingAgents graph behavior, not terminal rendering code.
