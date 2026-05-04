# TradeMaster Roadmap

This is the working build order for TradeMaster after the v1.2 local persistence foundation. The product direction is a personal private-office platform with three control surfaces:

- Webull-centered human-managed trading with AI research and strategy support.
- Alpaca/Plaid/provider-backed agent research and account context.
- A separate AI-managed high-risk portfolio harness with isolated funding, paper proving, symbolic vetoes, monitoring, and a kill switch.

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

## 14. Build Webull Handoff Workflow

Support human-managed trading workflow.

- Generate handoff cards for Webull.
- Track manual execution status.
- Let the user record fills or rejected ideas.
- Keep Webull automation separate from the high-risk AI harness.

## 15. Add High-Risk AI Harness

Only after paper proving, symbolic constraints, and provider instrumentation are stable.

- Dedicated paper account first.
- Separate high-risk funding mandate.
- Continuous monitoring.
- Hard kill switch.
- Daily summary and exception alerts.
- Live funds only after explicit configuration.

## 16. Add Tax And Attorney Briefing Layer

Make Pillar 2 attorney-friendly.

- Output questions and option trees, not advice-shaped recommendations.
- Cite rules, jurisdictions, effective dates, and data anchors.
- Generate Markdown/PDF briefs for attorney triage.
- Track attorney/bookkeeper feedback as durable records.

## 17. Add Document Vault

Store and reason over paperwork safely.

- Metadata first.
- Encrypted attachments later.
- Source, date, confidence, advisor, and renewal fields.
- Link documents to assets, goals, providers, and tax issues.

## 18. Add Retrieval Layer

Add local retrieval before pgvector.

- SQLite FTS and/or sqlite-vec for local retrieval.
- Embed reports, advisor notes, tax memos, and documents.
- Keep relational records as truth.
- Migrate to Postgres + pgvector when scale or deployment needs justify it.

## 19. Add Mobile/Mac Clients

After the local API is stable.

- iOS app for approvals, alerts, digests, and goal review.
- macOS app for local server control and notifications.
- Remote clients call the TradeMaster API; they do not read Keychain directly.

## 20. Add Galvo/Coalesce Integration

When ready.

- Route LLM calls through Galvo/Coalesce.
- Keep LangGraph as the current workflow runtime until Galvo is production-ready.
- Preserve LangFuse observability and TradeMaster business ledger.
