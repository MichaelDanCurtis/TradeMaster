# Local Persistence, Secret Store, And Ledger Design

## Decision

TradeMaster v1.2 uses SQLite as the local system of record and keeps Postgres with pgvector as the planned migration target. SQLite is the right immediate choice because the backend already uses SQLModel/SQLAlchemy against SQLite for run events, approvals, decisions, and broker order records. The highest-risk v1.2 problem is preserving an auditable local ledger, not scaling vector retrieval.

The schema must remain boring and portable. New tables should avoid SQLite-specific behavior where possible, and repository methods should keep enough structure that a future Postgres/pgvector backend can reuse the same domain contracts.

## Storage Profile

The local profile is:

- SQLite for durable relational state.
- SQLModel models and repository methods as the access layer.
- LangGraph SQLite checkpoints for workflow recovery only.
- Optional SQLite FTS/vector search later for local retrieval.

The future power profile is:

- Postgres as the relational system of record.
- pgvector for report, document, memory, and advisor-note retrieval.
- The same provider, ledger, goal, asset, and approval contracts.

TradeMaster does not start with Neo4j or a graph database. Graph behavior is modeled through entity and edge records first.

## Provider Roles

Provider records must distinguish roles and authority:

- Alpaca Market Data: first reliable source for agent-facing trade and market data.
- Alpaca Paper Broker: first real broker adapter, paper-only by default.
- Webull Market Data / Broker: human trading cockpit and future handoff surface, not the first automation dependency.
- Plaid Investments / Banking: read-only banking, balances, holdings, securities, transactions, and account context.
- LLM providers: OpenAI, Anthropic, and future provider routing through Galvo/Coalesce.

The read path and write path stay separate. Plaid never executes transfers or trades. Brokers never become the canonical aggregated account sensor.

## Portfolio Control Modes

TradeMaster supports two separate trading-control modes:

- Human-managed assisted trading: agents produce research, suggestions, order previews, and Webull/Alpaca handoff records. The user approves every trade before broker submission.
- AI-managed high-risk portfolios: agents may manage a dedicated high-risk portfolio under an explicit mandate. This mode requires a separate account boundary, separate configuration flag, symbolic vetoes, position caps, drawdown limits, daily turnover limits, observability, and a kill switch. It is never enabled by default and is never mixed with normal personal accounts.

Webull is the primary human-managed strategy and trading surface. The AI agent harness is the separate high-risk portfolio surface. The high-risk portfolio must have explicit funding limits, paper-mode proving, account isolation, and ledger-visible mandate controls before it can receive real funds.

The UI and ledger must show the control mode on every run, recommendation, approval, and order intent. A high-risk portfolio can be paper-tested first and later mapped to a real account only after explicit configuration and deliberately sized funding.

## Secret Store

The database stores provider configuration and `secret_ref` values only. Raw API keys, OAuth tokens, broker credentials, and refresh tokens are never stored in SQLite.

The v1.2 secret-store interface is:

- `get_secret(secret_ref)`
- `set_secret(secret_ref, value)`
- `delete_secret(secret_ref)`
- `describe_secret(secret_ref)`

Initial implementations:

- `EnvSecretStore` for tests and simple development.
- `MacKeychainSecretStore` for the MacBook server.

Remote clients do not read Keychain directly. They call the TradeMaster API, and the MacBook server resolves secrets locally when a provider needs them. A later hosted profile can add OnePassword, Infisical, Vault, AWS Secrets Manager, or another remote backend without changing provider records.

## Event Ledger

LangGraph checkpoints and LangFuse traces are not the product ledger.

- LangGraph checkpoint: workflow resume and recovery.
- LangFuse trace: observability, debugging, model cost, and graph inspection.
- TradeMaster ledger: durable business and audit record.

The v1.2 ledger stores events such as:

- `agent.run.started`
- `agent.message.created`
- `a2ui.surface.emitted`
- `provider.configured`
- `provider.health.checked`
- `portfolio.mandate.created`
- `portfolio.control_mode.changed`
- `goal.created`
- `asset.dossier.updated`
- `approval.requested`
- `decision.recorded`
- `snapshot.created`

Ledger events are append-only and can link to runs, providers, goals, assets, documents, or trade intents through entity references.

## Entity Graph

The graph model starts as relational records:

- `private_office_entities`: typed nodes such as person, agent, provider, account, goal, asset, report, document, rule, and decision.
- `private_office_edges`: typed relationships such as owns, funds, requires, references, blocks, advised_by, approved_by, derived_from, and affects.

This is enough for the private-office product to answer questions like:

- Which accounts fund this goal?
- Which tax blockers affect this asset?
- Which advisor note supports this report?
- Which provider produced this data?
- Which decision affected this goal?

## Goals And Asset Dossiers

Goals and asset dossiers should become editable data, not only seeded frontend records. The first durable model should support:

- user-created goals
- yacht, property, vehicle, firearms, equipment, and account-linked asset dossiers
- blocker records owned by tax, insurance, property, or capital teams
- Plaid-linked funding context later
- agent-suggested changes that remain approval-gated

## Backup Posture

Backups should be snapshot-based and encrypted before offsite storage.

The first implementation creates a snapshot manifest that records:

- snapshot id
- database path
- storage profile
- creation timestamp
- SHA-256 hashes for included files
- whether encryption was requested
- offsite target label

The first slice does not need to push to a remote provider. It must create a deterministic manifest and leave a clear extension point for age/sops-style encryption and offsite upload.

## Non-Goals For v1.2

- No live Alpaca or Webull credentials.
- No broker execution beyond existing fake paper broker behavior.
- No Plaid Link flow yet.
- No autonomous high-risk portfolio execution yet.
- No pgvector runtime dependency.
- No graph database runtime dependency.
- No direct remote access to Keychain from browser clients.

## Acceptance

- The vision/roadmap documents record SQLite-first with a pgvector migration target.
- Provider configuration is durable and stores `secret_ref`, not raw secrets.
- A secret-store abstraction exists with testable non-Keychain behavior.
- A private-office ledger can append/list generic events.
- Entity and edge records can model graph-like relationships.
- Snapshot manifest generation exists and is covered by tests.
