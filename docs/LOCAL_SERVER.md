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
