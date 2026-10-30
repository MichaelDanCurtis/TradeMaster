# TradeMaster

A local research and paper-trading workbench built on [TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents).

TradeMaster combines a Next.js dashboard with a Python API, research workers,
forecast experiments, portfolio diagnostics, and approval-gated Alpaca paper execution.
It is experimental software. The historical experiments have **not established a
reliable advantage over SPY**; model output and simulated returns are research evidence,
not promises of profit.

## Run locally

Use Python 3.12, Node.js 22, [uv](https://docs.astral.sh/uv/), and tmux.

```sh
git clone https://github.com/MichaelDanCurtis/TradeMaster.git
cd TradeMaster
cp .env.example .env
uv sync --frozen --extra dev
npm ci
npm run dev:local
```

Open http://127.0.0.1:3000. The API listens on http://127.0.0.1:8797.
Stop services with `npm run stop:local`.

The UI can start without provider credentials. Configure providers explicitly in
Settings when you want real data or model calls. Store secrets in environment variables
or the macOS Keychain; never put them in source files or screenshots. See
[local setup](docs/LOCAL_SERVER.md) for provider wiring and worker operation.

**Keep this application on localhost.** It is a single-user workbench without
multi-user authentication. Room headers and approval controls are not an authentication
boundary. Do not expose it through public hosting, tunnels, or an unauthenticated proxy.
Publishing this repository does not publish a hosted trading service.

## Capabilities and limits

- Research explorer, source evidence, strategy drafts, and historical comparisons.
- Local forecasting experiments; model weights and private datasets are not included.
- Portfolio/account observations and paper-order scheduling with explicit approvals.
- Preserved experiment contracts and evidence gaps. Tests and successful API calls do
  not establish an investment edge or successful broker execution.

Optional forecast environments, external models, Docker/LEAN, and provider accounts
have their own setup and license requirements. Download no model until you have reviewed
its terms. [Forecast lab](docs/FORECAST_LAB.md) and [research overview](docs/QUANT_RESEARCH_DESIGN.md)
provide more detail. Some historical notes refer to local artifacts and operational
reports deliberately excluded from the public repository.

## Checks

```sh
uv run --frozen --extra dev python -m pytest tests -m "not integration"
npm --workspace apps/web test
npm run web:build
gitleaks git . --redact
```

See [SECURITY.md](SECURITY.md) for security boundaries and vulnerability reporting,
and [CONTRIBUTING.md](CONTRIBUTING.md) before sharing changes or data.

## License and attribution

Apache-2.0; see [LICENSE](LICENSE) and [NOTICE](NOTICE). The original TradingAgents
README is preserved in [README.upstream.md](README.upstream.md). TradeMaster is an
independent derivative, not an official TauricResearch release. Third-party notices
are retained under `docs/third-party/`; model weights retain their separate licenses.
