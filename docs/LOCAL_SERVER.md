# Local Server

TradeMaster is intended to run as a local MacBook server during this phase. The web app and FastAPI backend should be started together so Settings, provider registry, snapshots, agent runs, and trade previews all point at the same local API.

Both HTTP servers bind to `127.0.0.1`. The application has no multi-user authentication;
do not expose it to public networks or a shared LAN.

## Start

```bash
npm run dev:local
```

This starts five tmux sessions:

- `trademaster-api`: FastAPI on `http://127.0.0.1:8797`
- `wealth-agents-web`: Next.js on `http://127.0.0.1:3000`
- `trademaster-research`: queued research jobs
- `trademaster-deployments`: account observation and deployment evaluation
- `trademaster-scheduler`: explicitly approved TWAP/DCA paper schedules

The script waits for both HTTP health checks and all three worker heartbeats before exiting. See [Paper execution scheduler](EXECUTION_SCHEDULER.md) for approval, timing, and cancellation behavior.

If `.venv`, `node_modules`, or the Next.js production build is missing, the script creates them before starting the tmux sessions.

## Stop

```bash
npm run stop:local
```

## Ports

Override ports when needed:

```bash
TRADEMASTER_API_PORT=8877 TRADEMASTER_WEB_PORT=3100 npm run dev:local
```

## Real TradingAgents Runs

Agent runs default to `execution_mode=simulated`. This keeps demos and UI tests
from accidentally spending tokens or calling live data providers.

The backend now has a real-run adapter for `TradingAgentsGraph.propagate()`, but
it is disabled by default. Enable it only after LLM and data-provider credentials
are configured:

```bash
TRADEMASTER_ENABLE_REAL_RUNS=1 npm run dev:local
```

If a client requests `execution_mode=real` while the adapter is disabled, the run
is recorded as `failed` with `reason=real_runner_not_configured` rather than
emitting simulated analyst events.

## Alpaca Market Data

Alpaca market data is read-only and agent-facing. Enable it in the provider
registry with a `secret_ref`; do not store raw keys in SQLite.

For local env-backed testing, store one JSON secret in an environment variable:

```bash
export TRADEMASTER_ALPACA_CREDS='{"key_id":"<paper key>","secret_key":"<paper secret>"}'
```

Then set `alpaca-market-data` to `enabled=true` with
`secret_ref=env:TRADEMASTER_ALPACA_CREDS`. The normalized API surface is:

- `GET /api/market-data/alpaca-market-data/bars`
- `GET /api/market-data/alpaca-market-data/quote`

The bars endpoint accepts `symbol`, `start`, `end`, `timeframe`, optional
`limit`, and optional `feed`. If `feed` is omitted, the backend uses the feed in
provider config, such as `{"feed":"iex"}`.

## Provider Secret Health

Settings can run a provider health check against the saved `secret_ref`:

```http
POST /api/provider-configs/alpaca-market-data/health-check
```

The response records only metadata such as backend and availability. It never
returns the resolved secret value. Each health check also writes a private-office
ledger event (`provider.health_checked`) for auditability.

## Plaid Read-Only Portfolio Data

Plaid is read-only in TradeMaster. The provider adapter normalizes accounts,
holdings, and transactions for private-office context; it does not expose any
write-capable banking or transfer operation.

For local env-backed testing, store one JSON secret:

```bash
export TRADEMASTER_PLAID_CREDS='{"client_id":"<client id>","secret":"<secret>","access_token":"<access token>"}'
```

Then set `plaid-investments` to `enabled=true` with
`secret_ref=env:TRADEMASTER_PLAID_CREDS`. The normalized API surface is:

- `GET /api/portfolio-data/plaid-investments/accounts`
- `GET /api/portfolio-data/plaid-investments/holdings`
- `GET /api/portfolio-data/plaid-investments/transactions?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD`

## Goals And Asset Dossiers

Goals and assets are durable private-office entities. They can be linked through
the entity graph so agents can connect material goals to assets, accounts,
documents, advisors, and later Plaid/Webull/Alpaca context.

- `GET /api/goals`
- `POST /api/goals`
- `GET /api/assets`
- `POST /api/assets`
- `GET /api/private-office/edges`
- `POST /api/private-office/edges`

## Symbolic Constraint Engine

The backend now has a deterministic constraint engine that can veto trade
previews before a broker intent is created. Current rules cover paper-mode
requirements, position concentration, sector concentration, daily turnover, and
drawdown circuit breakers. The broker service accepts the engine as an optional
gate; wiring it to durable portfolio mandates is the next step.

## Portfolio Mandates

Portfolio mandates describe who controls a portfolio and which guardrails apply.
This is where Webull human-assisted strategy and the Alpaca AI high-risk paper
harness become explicit durable records.

- `GET /api/portfolio-mandates`
- `GET /api/portfolio-mandates?control_mode=ai-managed-high-risk`
- `POST /api/portfolio-mandates`

High-risk AI mandates are rejected unless paper proving and the kill switch are
enabled.

## Alpaca Paper Broker Adapter

The Alpaca broker adapter is paper-only. It submits market notional orders to
the Alpaca paper endpoint and relies on the existing TradeMaster flow for
preview, approval, symbolic constraint checks, and audit persistence.

For local env-backed testing, store one JSON secret:

```bash
export TRADEMASTER_ALPACA_BROKER_CREDS='{"key_id":"<paper key>","secret_key":"<paper secret>"}'
```

Live trading is not wired into this adapter.

## Observability And LangFuse

Every agent run now creates a durable local observability trace with the
TradeMaster run id, execution mode, selected LLM provider/models, broker mode,
analysts, status, and failure reason when applicable.

- `GET /api/runs/{run_id}/trace`
- `POST /api/runs/{run_id}/trace/export`

LangFuse is registered as `langfuse-observability` in the provider registry so
credentials can use the same `secret_ref` and health-check flow as other
providers. External trace export is intentionally separated from the local trace
ledger; the local ledger remains the business truth.

For local env-backed testing, store one JSON secret:

```bash
export TRADEMASTER_LANGFUSE_CREDS='{"public_key":"<pk-lf...>","secret_key":"<sk-lf...>","base_url":"https://cloud.langfuse.com"}'
```

Then set `langfuse-observability` to `enabled=true` with
`secret_ref=env:TRADEMASTER_LANGFUSE_CREDS`. Export uses the LangFuse Python SDK
when that package is installed. If it is not installed, the API returns a
controlled `503` and the local trace remains intact.

## Encrypted Backups

The snapshot endpoint can create either a manifest-only record or an encrypted
local backup artifact. The encrypted path uses AES-256-GCM, derives the key from
a server-side secret reference, stores only artifact metadata in SQLite, and
records `snapshot.created` / `snapshot.verified` events in the private-office
ledger.

For local env-backed testing, store a backup key:

```bash
export TRADEMASTER_BACKUP_KEY='<long local backup passphrase>'
```

Then call:

```http
POST /api/snapshots
{
  "backup_key_ref": "env:TRADEMASTER_BACKUP_KEY",
  "offsite_target": "manual-offsite"
}
```

This writes an encrypted `.tmbackup` file next to the SQLite database under
`backups/`. Restore verification is available without exposing key material:

```http
POST /api/snapshots/{snapshot_id}/verify
{
  "backup_key_ref": "env:TRADEMASTER_BACKUP_KEY"
}
```

## Requirements

These are still useful to run manually in a fresh checkout, but `npm run dev:local` will bootstrap them if they are missing:

```bash
npm install
uv sync --extra dev
```

## What This Does Not Do Yet

- It does not daemonize services outside tmux.
- It does not create a LaunchAgent.
- It does not expose the MacBook server remotely.
- It does not manage TLS.

Those are later deployment steps after the local API contracts stabilize.
