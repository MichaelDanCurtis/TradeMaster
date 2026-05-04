# Local Server

TradeMaster is intended to run as a local MacBook server during this phase. The web app and FastAPI backend should be started together so Settings, provider registry, snapshots, agent runs, and trade previews all point at the same local API.

## Start

```bash
npm run dev:local
```

This starts two tmux sessions:

- `trademaster-api`: FastAPI on `http://127.0.0.1:8787`
- `wealth-agents-web`: Next.js on `http://127.0.0.1:3000`

The script waits for both health checks before exiting.

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
