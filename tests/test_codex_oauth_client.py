import json
from pathlib import Path

import pytest

from tradingagents.llm_clients.codex_oauth_client import (
    CODEX_RESPONSES_BASE_URL,
    CodexOAuthAuthError,
    CodexOAuthChat,
    CodexOAuthClient,
)
from tradingagents.llm_clients.factory import create_llm_client


def _write_auth(path: Path, *, access_token: str = "tok_access", account_id: str = "acc_id") -> Path:
    path.write_text(
        json.dumps(
            {
                "auth_mode": "chatgpt",
                "OPENAI_API_KEY": None,
                "tokens": {
                    "id_token": "id",
                    "access_token": access_token,
                    "refresh_token": "rt_x",
                    "account_id": account_id,
                },
                "last_refresh": "2026-05-07T19:24:23.880138Z",
            }
        )
    )
    return path


def test_factory_returns_codex_oauth_client():
    client = create_llm_client("codex-oauth", "gpt-5.4-mini")
    assert isinstance(client, CodexOAuthClient)


def test_get_llm_reads_auth_file_and_configures_responses_api(tmp_path: Path):
    auth_file = _write_auth(tmp_path / "auth.json", access_token="tok_X", account_id="acc_42")
    client = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file))

    chat = client.get_llm()

    assert isinstance(chat, CodexOAuthChat)
    assert chat.model_name == "gpt-5.4-mini"
    # ChatOpenAI keeps the api key in a SecretStr; coerce to string.
    assert chat.openai_api_key.get_secret_value() == "tok_X"
    assert str(chat.openai_api_base) == CODEX_RESPONSES_BASE_URL
    assert chat.default_headers == {"chatgpt-account-id": "acc_42"}
    assert chat.use_responses_api is True
    assert chat.streaming is True


def test_get_llm_respects_codex_auth_file_env(monkeypatch, tmp_path: Path):
    auth_file = _write_auth(tmp_path / "env_auth.json", access_token="tok_env", account_id="acc_env")
    monkeypatch.setenv("CODEX_AUTH_FILE", str(auth_file))

    chat = CodexOAuthClient(model="gpt-5.4-mini").get_llm()

    assert chat.openai_api_key.get_secret_value() == "tok_env"
    assert chat.default_headers == {"chatgpt-account-id": "acc_env"}


def test_get_llm_raises_when_auth_file_missing(tmp_path: Path):
    client = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(tmp_path / "nope.json"))

    with pytest.raises(CodexOAuthAuthError, match="auth file not found"):
        client.get_llm()


def test_get_llm_raises_when_tokens_incomplete(tmp_path: Path):
    auth_file = tmp_path / "auth.json"
    auth_file.write_text(json.dumps({"tokens": {"access_token": "tok_only"}}))
    client = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file))

    with pytest.raises(CodexOAuthAuthError, match="missing access_token or account_id"):
        client.get_llm()


def test_request_payload_strips_unsupported_params_and_forces_store_stream(tmp_path: Path):
    auth_file = _write_auth(tmp_path / "auth.json")
    chat = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file)).get_llm()

    payload = chat._get_request_payload(
        [{"role": "user", "content": "hi"}],
        stop=None,
        max_tokens=512,
        max_output_tokens=512,
        max_completion_tokens=512,
        store=True,
        stream=False,
    )

    assert "max_tokens" not in payload
    assert "max_output_tokens" not in payload
    assert "max_completion_tokens" not in payload
    assert payload["store"] is False
    assert payload["stream"] is True


def test_request_payload_promotes_system_messages_to_instructions(tmp_path: Path):
    auth_file = _write_auth(tmp_path / "auth.json")
    chat = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file)).get_llm()

    payload = chat._get_request_payload(
        [
            {"role": "system", "content": "Be terse."},
            {"role": "system", "content": [{"type": "text", "text": "Use English."}]},
            {"role": "user", "content": "hi"},
        ],
        stop=None,
    )

    assert payload["instructions"] == "Be terse.\n\nUse English."
    assert all(item.get("role") != "system" for item in payload["input"])
    assert any(item.get("role") == "user" for item in payload["input"])


def test_request_payload_supplies_default_instructions_when_none_present(tmp_path: Path):
    auth_file = _write_auth(tmp_path / "auth.json")
    chat = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file)).get_llm()

    payload = chat._get_request_payload(
        [{"role": "user", "content": "hi"}],
        stop=None,
    )

    # Endpoint requires non-empty instructions even when caller didn't set one.
    assert payload["instructions"]
    assert isinstance(payload["instructions"], str)


def test_validate_model_accepts_known_codex_slugs_and_rejects_others(tmp_path: Path):
    auth_file = _write_auth(tmp_path / "auth.json")
    accepted = CodexOAuthClient(model="gpt-5.4-mini", auth_file=str(auth_file))
    rejected = CodexOAuthClient(model="gpt-4o", auth_file=str(auth_file))

    assert accepted.validate_model() is True
    assert rejected.validate_model() is False
