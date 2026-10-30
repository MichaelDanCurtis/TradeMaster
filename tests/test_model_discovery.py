import json
from pathlib import Path

import httpx
import pytest

from tradingagents.llm_clients import model_discovery
from tradingagents.llm_clients.model_discovery import (
    ANTHROPIC_STATIC_MODELS,
    discover_models,
)


def _write_codex_cache(path: Path, slugs: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "fetched_at": "2026-05-10T00:00:00Z",
                "client_version": "1.0",
                "models": [{"slug": slug, "display_name": slug} for slug in slugs],
            }
        )
    )


def test_codex_discovery_reads_cache_file(monkeypatch, tmp_path: Path):
    cache = tmp_path / "auth" / "models_cache.json"
    _write_codex_cache(cache, ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"])
    monkeypatch.setenv("CODEX_MODELS_CACHE", str(cache))

    result = discover_models(provider="codex-oauth", base_url=None, api_key=None)

    assert result.source == "codex_cache"
    assert result.models == ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini"]


def test_codex_discovery_reports_unavailable_when_cache_missing(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("CODEX_MODELS_CACHE", str(tmp_path / "absent.json"))

    result = discover_models(provider="codex-oauth", base_url=None, api_key=None)

    assert result.source == "unavailable"
    assert result.models == []
    assert "not found" in (result.detail or "")


def test_anthropic_discovery_returns_static_list():
    result = discover_models(provider="anthropic", base_url=None, api_key=None)

    assert result.source == "static"
    assert tuple(result.models) == ANTHROPIC_STATIC_MODELS


def test_openai_compatible_discovery_parses_data_array(monkeypatch):
    def fake_get(url, headers, timeout):
        assert url == "https://api.example.com/v1/models"
        assert headers["Authorization"] == "Bearer sk-test"
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json={
                "object": "list",
                "data": [
                    {"id": "gpt-foo", "object": "model"},
                    {"id": "gpt-bar", "object": "model"},
                    {"id": ""},  # ignored
                ],
            },
        )

    monkeypatch.setattr(model_discovery.httpx, "get", fake_get)

    result = discover_models(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        api_key="sk-test",
    )

    assert result.source == "api"
    assert result.models == ["gpt-foo", "gpt-bar"]


def test_openai_compatible_discovery_returns_unavailable_on_non_200(monkeypatch):
    def fake_get(url, headers, timeout):
        return httpx.Response(401, request=httpx.Request("GET", url), json={"error": "nope"})

    monkeypatch.setattr(model_discovery.httpx, "get", fake_get)

    result = discover_models(
        provider="openai-compatible",
        base_url="https://api.example.com/v1",
        api_key=None,
    )

    assert result.source == "unavailable"
    assert result.models == []
    assert "401" in (result.detail or "")


def test_openai_compatible_discovery_returns_unavailable_on_network_error(monkeypatch):
    def fake_get(url, headers, timeout):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(model_discovery.httpx, "get", fake_get)

    result = discover_models(
        provider="openai-compatible",
        base_url="http://127.0.0.1:1234/v1",
        api_key=None,
    )

    assert result.source == "unavailable"
    assert result.models == []
    assert "network error" in (result.detail or "")


def test_discovery_without_base_url_reports_unavailable():
    result = discover_models(provider="openai-compatible", base_url=None, api_key=None)
    assert result.source == "unavailable"
    assert result.models == []
