from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app
from tradingagents.ui.db import create_session_factory
from tradingagents.ui.events import RunConfig, RunEvent
from tradingagents.ui.market_data.base import MarketDataBar, MarketDataQuote
from tradingagents.ui.portfolio_data.base import (
    PortfolioAccount,
    PortfolioHolding,
    PortfolioTransaction,
)
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.runner import RealRunResult


class FakeLangfuseObservation:
    trace_id = "0123456789abcdef0123456789abcdef"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None

    def update(self, **kwargs) -> None:
        return None


class FakeLangfuseClient:
    def create_trace_id(self, seed: str) -> str:
        return "0123456789abcdef0123456789abcdef"

    def start_as_current_observation(self, **kwargs):
        return FakeLangfuseObservation()

    def get_trace_url(self, *, trace_id: str) -> str:
        return f"https://cloud.langfuse.com/project/local/traces/{trace_id}"

    def flush(self) -> None:
        return None


def test_health_endpoint_returns_ok(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "tradingagents-ui"}


def test_provider_registry_endpoint_returns_roles_and_capabilities(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/providers")

    assert response.status_code == 200
    providers = response.json()["providers"]
    by_id = {provider["id"]: provider for provider in providers}

    assert by_id["simulated-market-data"]["status"] == "available"
    assert by_id["simulated-market-data"]["role"] == "market-data"
    assert "historical-bars" in by_id["alpaca-market-data"]["capabilities"]
    assert by_id["webull-market-data"]["status"] == "planned"
    assert "historical-bars" in by_id["webull-market-data"]["capabilities"]
    assert by_id["webull-broker"]["role"] == "brokerage"
    assert by_id["fake-paper-broker"]["role"] == "brokerage"
    assert by_id["plaid-investments"]["status"] == "needs_key"
    assert by_id["openai-llm"]["role"] == "llm"


def test_provider_config_endpoint_updates_secret_reference(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    updated = client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "keychain:alpaca:paper",
            "config": {"feed": "iex", "raw_secret": "must-not-survive"},
        },
    )
    listed = client.get("/api/provider-configs")
    by_id = {provider["provider_id"]: provider for provider in listed.json()["providers"]}

    assert updated.status_code == 200
    assert updated.json()["secret_ref"] == "keychain:alpaca:paper"
    assert "raw_secret" not in updated.json()["config"]
    assert by_id["alpaca-market-data"]["enabled"] is True


def test_provider_secret_health_check_reports_availability_and_audits(
    tmp_path: Path,
    monkeypatch,
):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    _, session_factory = create_session_factory(database_url)
    repo = UiRepository(session_factory)
    monkeypatch.setenv("TRADEMASTER_ALPACA_CREDS", "not-returned")
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.post("/api/provider-configs/alpaca-market-data/health-check")
    events = repo.list_private_office_events()

    assert response.status_code == 200
    assert response.json()["health"]["secret"] == {
        "backend": "env",
        "available": True,
    }
    assert "not-returned" not in str(response.json())
    assert events[-1].event_type == "provider.health_checked"
    assert events[-1].actor == "Provider Registry"
    assert events[-1].entity_id == "provider_alpaca_market_data"
    assert events[-1].payload["secret_available"] is True


def test_provider_secret_health_check_reports_missing_secret(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:MISSING_TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.post("/api/provider-configs/alpaca-market-data/health-check")

    assert response.status_code == 200
    assert response.json()["status"] == "needs_key"
    assert response.json()["health"]["secret"] == {
        "backend": "env",
        "available": False,
    }


def test_private_office_event_endpoint_appends_ledger_event(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/private-office/events",
        json={
            "event_type": "agent.message.created",
            "summary": "Goals team updated the yacht dossier.",
            "actor": "Goal Steward",
            "entity_id": "goal_yacht",
            "payload": {"surface": "goal-dossier"},
        },
    )

    assert response.status_code == 200
    assert response.json()["event_type"] == "agent.message.created"
    assert response.json()["payload"] == {"surface": "goal-dossier"}


def test_goal_endpoints_create_and_list_durable_goal_dossiers(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/goals",
        json={
            "goal_id": "goal_yacht",
            "label": "Absolute Navetta 68",
            "target_amount": 4750000,
            "target_date": "2026-11-01",
            "status": "planning",
            "payload": {"location": "Hawaii", "advisor_notes": ["Review ownership structure"]},
        },
    )
    listed = client.get("/api/goals")

    assert created.status_code == 200
    assert created.json()["entity_id"] == "goal_yacht"
    assert created.json()["entity_type"] == "goal"
    assert created.json()["payload"]["target_amount"] == 4750000
    assert listed.status_code == 200
    assert listed.json()["goals"][0]["label"] == "Absolute Navetta 68"


def test_asset_endpoints_create_and_list_durable_asset_dossiers(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/assets",
        json={
            "asset_id": "asset_navetta_68",
            "label": "Absolute Navetta 68",
            "asset_type": "boat",
            "jurisdiction": "Hawaii",
            "status": "target",
            "payload": {"liability_notes": ["Moorage and insurance review required"]},
        },
    )
    listed = client.get("/api/assets")

    assert created.status_code == 200
    assert created.json()["entity_id"] == "asset_navetta_68"
    assert created.json()["entity_type"] == "asset"
    assert created.json()["payload"]["asset_type"] == "boat"
    assert listed.status_code == 200
    assert listed.json()["assets"][0]["payload"]["jurisdiction"] == "Hawaii"


def test_private_office_edge_endpoint_links_goal_to_asset(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/goals",
        json={"goal_id": "goal_yacht", "label": "Absolute Navetta 68"},
    )
    client.post(
        "/api/assets",
        json={
            "asset_id": "asset_navetta_68",
            "label": "Absolute Navetta 68",
            "asset_type": "boat",
        },
    )

    created = client.post(
        "/api/private-office/edges",
        json={
            "source_entity_id": "goal_yacht",
            "target_entity_id": "asset_navetta_68",
            "relationship": "targets_asset",
            "payload": {"confidence": "candidate"},
        },
    )
    listed = client.get(
        "/api/private-office/edges",
        params={"source_entity_id": "goal_yacht"},
    )

    assert created.status_code == 200
    assert created.json()["relationship"] == "targets_asset"
    assert listed.status_code == 200
    assert listed.json()["edges"][0]["target_entity_id"] == "asset_navetta_68"


def test_portfolio_mandate_endpoints_create_and_filter_mandates(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    human = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "Webull assisted strategy",
            "control_mode": "human-managed-assisted",
            "account_ref": "webull:human",
            "funding_limit": 250000,
            "max_position_percent": 20,
            "max_drawdown_percent": 12,
            "daily_turnover_limit_percent": 15,
            "paper_mode_required": False,
            "kill_switch_enabled": True,
            "status": "active",
        },
    )
    high_risk = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "AI high-risk paper harness",
            "control_mode": "ai-managed-high-risk",
            "account_ref": "alpaca:paper:high-risk",
            "funding_limit": 50000,
            "max_position_percent": 10,
            "max_drawdown_percent": 8,
            "daily_turnover_limit_percent": 20,
            "paper_mode_required": True,
            "kill_switch_enabled": True,
            "status": "draft",
            "payload": {"proving_phase": "paper"},
        },
    )
    filtered = client.get(
        "/api/portfolio-mandates",
        params={"control_mode": "ai-managed-high-risk"},
    )

    assert human.status_code == 200
    assert human.json()["control_mode"] == "human-managed-assisted"
    assert high_risk.status_code == 200
    assert high_risk.json()["paper_mode_required"] is True
    assert filtered.status_code == 200
    assert [item["name"] for item in filtered.json()["mandates"]] == [
        "AI high-risk paper harness"
    ]


def test_portfolio_mandate_endpoint_rejects_high_risk_without_kill_switch(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.post(
        "/api/portfolio-mandates",
        json={
            "name": "AI high-risk unsafe",
            "control_mode": "ai-managed-high-risk",
            "account_ref": "alpaca:paper:high-risk",
            "funding_limit": 50000,
            "max_position_percent": 10,
            "max_drawdown_percent": 8,
            "daily_turnover_limit_percent": 20,
            "paper_mode_required": True,
            "kill_switch_enabled": False,
        },
    )

    assert response.status_code == 400
    assert "kill switch" in response.json()["detail"]


def test_snapshot_endpoint_creates_manifest_for_local_sqlite(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))

    response = client.post(
        "/api/snapshots",
        json={"encryption_mode": "age", "offsite_target": "backblaze-b2"},
    )

    assert response.status_code == 200
    assert response.json()["storage_profile"] == "sqlite-local"
    assert response.json()["encryption_mode"] == "age"
    assert response.json()["manifest"]["files"][0]["path"] == str(tmp_path / "ui.db")
    assert len(response.json()["manifest"]["files"][0]["sha256"]) == 64


def test_snapshot_endpoint_creates_encrypted_bundle_from_secret_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TRADEMASTER_BACKUP_KEY", "local backup key")
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))

    response = client.post(
        "/api/snapshots",
        json={
            "backup_key_ref": "env:TRADEMASTER_BACKUP_KEY",
            "offsite_target": "manual-offsite",
        },
    )

    assert response.status_code == 200
    body = response.json()
    artifact = body["manifest"]["backup_artifact"]
    artifact_path = Path(artifact["path"])
    assert body["encryption_mode"] == "local-aes-256-gcm"
    assert artifact["algorithm"] == "AES-256-GCM"
    assert artifact_path.exists()
    assert b"sqlite_master" not in artifact_path.read_bytes()
    assert "local backup key" not in str(body)


def test_snapshot_verify_endpoint_checks_encrypted_bundle_from_secret_ref(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("TRADEMASTER_BACKUP_KEY", "local backup key")
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    created = client.post(
        "/api/snapshots",
        json={"backup_key_ref": "env:TRADEMASTER_BACKUP_KEY"},
    ).json()

    verification = client.post(
        f"/api/snapshots/{created['snapshot_id']}/verify",
        json={"backup_key_ref": "env:TRADEMASTER_BACKUP_KEY"},
    )

    assert verification.status_code == 200
    assert verification.json()["valid"] is True
    assert verification.json()["manifest"]["snapshot_id"] == created["snapshot_id"]
    assert verification.json()["files"][0]["verified"] is True


def test_market_data_bars_endpoint_returns_normalized_provider_data(tmp_path: Path):
    class FakeMarketDataProvider:
        def historical_bars(self, **kwargs):
            return [
                MarketDataBar(
                    symbol=kwargs["symbol"].upper(),
                    timestamp=datetime(2026, 4, 30, 13, 30, tzinfo=timezone.utc),
                    open=838.12,
                    high=841.0,
                    low=836.5,
                    close=839.05,
                    volume=6601542,
                    vwap=838.71,
                    trade_count=9342,
                )
            ]

        def latest_quote(self, symbol: str, *, feed: str | None = None):
            raise AssertionError("not used")

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_providers={"alpaca-market-data": FakeMarketDataProvider()},
        )
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/bars",
        params={
            "symbol": "nvda",
            "start": "2026-04-30T13:30:00Z",
            "end": "2026-04-30T20:00:00Z",
            "timeframe": "1Min",
            "limit": "100",
            "feed": "iex",
        },
    )

    assert response.status_code == 200
    assert response.json()["bars"][0]["symbol"] == "NVDA"
    assert response.json()["bars"][0]["timestamp"] == "2026-04-30T13:30:00Z"
    assert response.json()["bars"][0]["vwap"] == 838.71


def test_market_data_quote_endpoint_returns_normalized_provider_data(tmp_path: Path):
    class FakeMarketDataProvider:
        def historical_bars(self, **kwargs):
            raise AssertionError("not used")

        def latest_quote(self, symbol: str, *, feed: str | None = None):
            return MarketDataQuote(
                symbol=symbol.upper(),
                timestamp=datetime(2026, 4, 30, 13, 30, 1, tzinfo=timezone.utc),
                bid_price=838.95,
                bid_size=200,
                ask_price=839.1,
                ask_size=300,
            )

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_providers={"alpaca-market-data": FakeMarketDataProvider()},
        )
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/quote",
        params={"symbol": "nvda", "feed": "iex"},
    )

    assert response.status_code == 200
    assert response.json()["quote"]["symbol"] == "NVDA"
    assert response.json()["quote"]["timestamp"] == "2026-04-30T13:30:01Z"
    assert response.json()["quote"]["ask_size"] == 300


def test_market_data_endpoint_builds_alpaca_provider_from_provider_config(
    tmp_path: Path,
    monkeypatch,
):
    class FakeResponse:
        def json(self):
            return {
                "bars": [
                    {
                        "t": "2026-04-30T13:30:00Z",
                        "o": 838.12,
                        "h": 841.0,
                        "l": 836.5,
                        "c": 839.05,
                        "v": 6601542,
                        "vw": 838.71,
                        "n": 9342,
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls = []

        def get(self, url: str, *, headers: dict, params: dict, timeout: float):
            self.calls.append(
                {
                    "url": url,
                    "headers": headers,
                    "params": params,
                    "timeout": timeout,
                }
            )
            return FakeResponse()

    monkeypatch.setenv(
        "TRADEMASTER_ALPACA_CREDS",
        '{"key_id":"paper-key","secret_key":"paper-secret"}',
    )
    http_client = RecordingHttpClient()
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            market_data_http_client=http_client,
        )
    )
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_ALPACA_CREDS",
            "config": {"feed": "iex"},
        },
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/bars",
        params={
            "symbol": "NVDA",
            "start": "2026-04-30T13:30:00Z",
            "end": "2026-04-30T20:00:00Z",
            "timeframe": "1Min",
        },
    )

    assert response.status_code == 200
    assert http_client.calls[0]["headers"] == {
        "APCA-API-KEY-ID": "paper-key",
        "APCA-API-SECRET-KEY": "paper-secret",
    }
    assert http_client.calls[0]["params"]["feed"] == "iex"


def test_market_data_endpoint_returns_controlled_error_when_secret_missing(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    client.post(
        "/api/provider-configs/alpaca-market-data",
        json={
            "enabled": True,
            "secret_ref": "env:MISSING_TRADEMASTER_ALPACA_CREDS",
        },
    )

    response = client.get(
        "/api/market-data/alpaca-market-data/quote",
        params={"symbol": "NVDA"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Market data secret is not available"}


def test_portfolio_data_endpoints_return_read_only_plaid_context(tmp_path: Path):
    class FakePortfolioProvider:
        def accounts(self):
            return [
                PortfolioAccount(
                    account_id="acc_1",
                    name="Brokerage",
                    type="investment",
                    subtype="brokerage",
                    current_balance=125000.25,
                    iso_currency_code="USD",
                )
            ]

        def holdings(self):
            return [
                PortfolioHolding(
                    account_id="acc_1",
                    security_id="sec_nvda",
                    symbol="NVDA",
                    name="NVIDIA Corporation",
                    quantity=12.5,
                    price=839.05,
                    value=10488.125,
                    cost_basis=8000.0,
                )
            ]

        def transactions(self, *, start_date: date, end_date: date):
            return [
                PortfolioTransaction(
                    transaction_id="txn_1",
                    account_id="acc_1",
                    date=start_date,
                    name="Deposit",
                    amount=-5000,
                    iso_currency_code="USD",
                    categories=["Transfer", "Deposit"],
                )
            ]

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            portfolio_providers={"plaid-investments": FakePortfolioProvider()},
        )
    )

    accounts = client.get("/api/portfolio-data/plaid-investments/accounts")
    holdings = client.get("/api/portfolio-data/plaid-investments/holdings")
    transactions = client.get(
        "/api/portfolio-data/plaid-investments/transactions",
        params={"start_date": "2026-04-01", "end_date": "2026-04-30"},
    )

    assert accounts.status_code == 200
    assert accounts.json()["accounts"][0]["current_balance"] == 125000.25
    assert holdings.status_code == 200
    assert holdings.json()["holdings"][0]["symbol"] == "NVDA"
    assert transactions.status_code == 200
    assert transactions.json()["transactions"][0]["categories"] == ["Transfer", "Deposit"]


def test_portfolio_data_endpoint_builds_plaid_provider_from_provider_config(
    tmp_path: Path,
    monkeypatch,
):
    class FakeResponse:
        def json(self):
            return {
                "accounts": [
                    {
                        "account_id": "acc_1",
                        "name": "Brokerage",
                        "type": "investment",
                        "balances": {
                            "current": 125000.25,
                            "iso_currency_code": "USD",
                        },
                    }
                ]
            }

        def raise_for_status(self):
            return None

    class RecordingHttpClient:
        def __init__(self) -> None:
            self.calls = []

        def post(self, url: str, *, json: dict, timeout: float):
            self.calls.append({"url": url, "json": json, "timeout": timeout})
            return FakeResponse()

    monkeypatch.setenv(
        "TRADEMASTER_PLAID_CREDS",
        '{"client_id":"client","secret":"sandbox-secret","access_token":"access-sandbox"}',
    )
    http_client = RecordingHttpClient()
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            portfolio_http_client=http_client,
        )
    )
    client.post(
        "/api/provider-configs/plaid-investments",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_PLAID_CREDS",
        },
    )

    response = client.get("/api/portfolio-data/plaid-investments/accounts")

    assert response.status_code == 200
    assert response.json()["accounts"][0]["account_id"] == "acc_1"
    assert "sandbox-secret" not in str(response.json())
    assert http_client.calls[0]["url"] == "https://production.plaid.com/accounts/balance/get"
    assert http_client.calls[0]["json"] == {
        "client_id": "client",
        "secret": "sandbox-secret",
        "access_token": "access-sandbox",
    }


def test_create_run_and_fetch_events(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    created = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    )
    run_id = created.json()["run_id"]
    events = client.get(f"/api/runs/{run_id}/events")

    assert created.status_code == 200
    assert created.json()["status"] == "completed"
    assert events.status_code == 200
    assert events.json()[0]["type"] == "run.created"


def test_fetch_run_observability_trace(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.get(f"/api/runs/{run_id}/trace")

    assert response.status_code == 200
    assert response.json()["run_id"] == run_id
    assert response.json()["status"] == "completed"
    assert response.json()["metadata"]["ticker"] == "NVDA"
    assert response.json()["metadata"]["execution_mode"] == "simulated"


def test_export_run_observability_trace_to_langfuse(tmp_path: Path, monkeypatch):
    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            langfuse_client_factory=lambda credentials: FakeLangfuseClient(),
        )
    )
    monkeypatch.setenv(
        "TRADEMASTER_LANGFUSE_CREDS",
        '{"public_key":"pk-lf-local","secret_key":"sk-lf-local","base_url":"https://cloud.langfuse.com"}',
    )
    client.post(
        "/api/provider-configs/langfuse-observability",
        json={
            "enabled": True,
            "secret_ref": "env:TRADEMASTER_LANGFUSE_CREDS",
        },
    )
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.post(f"/api/runs/{run_id}/trace/export")

    assert response.status_code == 200
    assert response.json()["provider"] == "langfuse-observability"
    assert response.json()["status"] == "exported"
    assert response.json()["external_trace_id"] == "0123456789abcdef0123456789abcdef"
    assert response.json()["metadata"]["exported_to"] == "langfuse"
    assert "sk-lf-local" not in str(response.json())


def test_export_run_observability_trace_requires_configured_langfuse_provider(
    tmp_path: Path,
):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "simulated",
        },
    ).json()["run_id"]

    response = client.post(f"/api/runs/{run_id}/trace/export")

    assert response.status_code == 403
    assert response.json() == {
        "detail": "LangFuse observability is disabled or missing a secret_ref"
    }


def test_create_real_run_uses_injected_real_runner(tmp_path: Path):
    class FakeRealRunner:
        def __call__(self, run_id: str, config: RunConfig) -> RealRunResult:
            return RealRunResult(
                events=[
                    RunEvent(
                        run_id=run_id,
                        sequence=1,
                        type="decision.created",
                        node="Portfolio Manager",
                        message=f"Created real decision for {config.ticker}.",
                        payload={"rating": "Neutral", "action": "Hold"},
                    )
                ],
                rating="Neutral",
                action="Hold",
                thesis="Injected real runner result.",
            )

    client = TestClient(
        create_app(
            f"sqlite:///{tmp_path / 'ui.db'}",
            real_runner=FakeRealRunner(),
        )
    )

    created = client.post(
        "/api/runs",
        json={
            "ticker": "NVDA",
            "trade_date": "2026-04-30",
            "execution_mode": "real",
        },
    )
    run_id = created.json()["run_id"]
    events = client.get(f"/api/runs/{run_id}/events")

    assert created.status_code == 200
    assert created.json()["status"] == "completed"
    assert [event["type"] for event in events.json()] == [
        "run.created",
        "run.started",
        "decision.created",
        "run.completed",
    ]


def test_stream_run_events_as_sse(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "AAPL", "trade_date": "2026-04-30"},
    ).json()["run_id"]

    response = client.get(f"/api/runs/{run_id}/stream")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: run.created" in response.text
    assert "event: run.completed" in response.text


def test_missing_run_events_return_404(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/runs/missing/events")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


def test_missing_run_stream_returns_404(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))

    response = client.get("/api/runs/missing/stream")

    assert response.status_code == 404
    assert response.json() == {"detail": "Run not found"}


def test_trade_ticket_preview_approval_and_submit(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]

    preview = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    )
    intent_id = preview.json()["intent_id"]
    blocked_submit = client.post(f"/api/trades/{intent_id}/submit")
    approval = client.post(
        f"/api/trades/{intent_id}/approve", json={"actor": "local-user"}
    )
    submitted = client.post(f"/api/trades/{intent_id}/submit")

    assert preview.status_code == 200
    assert preview.json()["environment"] == "paper"
    assert blocked_submit.status_code == 403
    assert approval.status_code == 200
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"


def test_disabled_run_rejects_trade_preview(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    ).json()["run_id"]

    response = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    )

    assert response.status_code == 403


def test_disabled_run_rejects_trade_approval(tmp_path: Path):
    database_url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(database_url))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "disabled"},
    ).json()["run_id"]
    _, session_factory = create_session_factory(database_url)
    repo = UiRepository(session_factory)
    intent = repo.create_trade_intent(
        run_id=run_id, symbol="NVDA", side="buy", notional=1000
    )

    response = client.post(
        f"/api/trades/{intent.intent_id}/approve", json={"actor": "local-user"}
    )

    assert response.status_code == 403
    assert not repo.has_approval(intent.intent_id)


def test_trade_ticket_preview_invalid_side_returns_validation_error(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]

    response = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "hold", "notional": 1000},
    )

    assert response.status_code == 422


def test_trade_ticket_duplicate_submit_returns_controlled_error(tmp_path: Path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'ui.db'}"))
    run_id = client.post(
        "/api/runs",
        json={"ticker": "NVDA", "trade_date": "2026-04-30", "broker_mode": "paper"},
    ).json()["run_id"]
    intent_id = client.post(
        "/api/trades/preview",
        json={"run_id": run_id, "symbol": "NVDA", "side": "buy", "notional": 1000},
    ).json()["intent_id"]

    client.post(f"/api/trades/{intent_id}/approve", json={"actor": "local-user"})
    submitted = client.post(f"/api/trades/{intent_id}/submit")
    duplicate = client.post(f"/api/trades/{intent_id}/submit")

    assert submitted.status_code == 200
    assert duplicate.status_code in (400, 403)
