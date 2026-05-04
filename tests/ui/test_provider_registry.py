from pathlib import Path

import pytest

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.providers import get_provider_catalog
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.secrets import EnvSecretStore, SecretNotFoundError


def _repo(tmp_path: Path) -> UiRepository:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return UiRepository(session_factory)


def test_provider_configs_seed_from_catalog_with_role_boundaries(tmp_path: Path):
    repo = _repo(tmp_path)

    configs = repo.list_provider_configs()
    by_id = {config.provider_id: config for config in configs}

    assert by_id["alpaca-market-data"].role == "market-data"
    assert by_id["alpaca-market-data"].control_surface == "agent-data"
    assert by_id["webull-market-data"].control_surface == "human-cockpit"
    assert by_id["webull-broker"].control_surface == "human-cockpit"
    assert by_id["plaid-investments"].role == "portfolio"
    assert by_id["plaid-investments"].write_authority == "read-only"
    assert by_id["alpaca-paper-broker"].write_authority == "paper-trading"


def test_provider_config_stores_secret_reference_not_secret_value(tmp_path: Path):
    repo = _repo(tmp_path)

    config = repo.upsert_provider_config(
        provider_id="alpaca-market-data",
        enabled=True,
        secret_ref="keychain:alpaca:paper",
        config={"feed": "iex", "raw_secret": "must-not-survive"},
        health={"status": "unchecked"},
    )
    reread = repo.get_provider_config("alpaca-market-data")

    assert config.secret_ref == "keychain:alpaca:paper"
    assert reread.secret_ref == "keychain:alpaca:paper"
    assert "raw_secret" not in reread.config
    assert not hasattr(reread, "secret_value")


def test_provider_catalog_documents_alpaca_webull_and_plaid_roles():
    catalog = get_provider_catalog()
    by_id = {provider.id: provider for provider in catalog.providers}

    assert "trade-stream" in by_id["alpaca-market-data"].capabilities
    assert by_id["alpaca-market-data"].control_surface == "agent-data"
    assert by_id["webull-market-data"].control_surface == "human-cockpit"
    assert by_id["webull-broker"].control_surface == "human-cockpit"
    assert by_id["plaid-investments"].primary_use.lower().startswith("read-only")


def test_env_secret_store_resolves_only_env_references(monkeypatch: pytest.MonkeyPatch):
    store = EnvSecretStore()
    monkeypatch.setenv("TRADEMASTER_ALPACA_KEY", "paper-key")

    assert store.get_secret("env:TRADEMASTER_ALPACA_KEY") == "paper-key"
    assert store.describe_secret("env:TRADEMASTER_ALPACA_KEY") == {
        "backend": "env",
        "available": True,
    }

    with pytest.raises(SecretNotFoundError):
        store.get_secret("env:MISSING_TRADEMASTER_SECRET")

    with pytest.raises(ValueError, match="env:"):
        store.get_secret("keychain:alpaca:paper")
