"""LangChain ChatModel that talks to the Codex CLI's ChatGPT-backed endpoint.

The Codex CLI ships an OAuth session for a ChatGPT account at
``~/.codex/auth.json``. That session is **not** accepted by the regular
``api.openai.com`` API (missing ``model.request`` scope), but it IS accepted by
``https://chatgpt.com/backend-api/codex/responses`` -- the same endpoint the
CLI itself calls. The endpoint speaks the OpenAI Responses API shape with a
few load-bearing constraints baked in by the ChatGPT-plan flow:

  * ``stream`` must be ``True``
  * ``store`` must be ``False``
  * ``max_output_tokens`` (and the legacy ``max_tokens`` /
    ``max_completion_tokens``) are rejected as unsupported parameters
  * the ``chatgpt-account-id`` header is required
  * only the ChatGPT-plan-flavored model slugs are accepted (gpt-5.X family,
    e.g. ``gpt-5.4-mini``); standard API model names are rejected
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

from .base_client import BaseLLMClient
from .openai_client import NormalizedChatOpenAI


CODEX_RESPONSES_BASE_URL = "https://chatgpt.com/backend-api/codex"
DEFAULT_AUTH_FILE = Path.home() / ".codex" / "auth.json"

# The chatgpt.com Codex endpoint rejects every flavour of output-length cap.
_STRIPPED_REQUEST_KEYS = frozenset(
    {"max_tokens", "max_output_tokens", "max_completion_tokens"}
)


class CodexOAuthAuthError(RuntimeError):
    """Raised when the Codex CLI auth session is missing or unusable."""


def _read_codex_auth(auth_file: Path) -> tuple[str, str]:
    """Return ``(access_token, account_id)`` from the Codex CLI auth file.

    The CLI refreshes ``auth.json`` automatically when invoked, so we read
    it fresh at client construction. Tokens live ~10 days; if the user
    hasn't run ``codex`` in that window, requests will 401 and the user
    needs to run ``codex login`` (or any ``codex`` command) to refresh.
    """
    if not auth_file.exists():
        raise CodexOAuthAuthError(
            f"Codex CLI auth file not found at {auth_file}. "
            "Run `codex login` to authenticate."
        )
    try:
        payload = json.loads(auth_file.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise CodexOAuthAuthError(
            f"Codex CLI auth file at {auth_file} is unreadable: {exc}"
        ) from exc
    tokens = payload.get("tokens") or {}
    access_token = tokens.get("access_token")
    account_id = tokens.get("account_id")
    if not access_token or not account_id:
        raise CodexOAuthAuthError(
            f"Codex CLI auth file at {auth_file} is missing access_token or "
            "account_id. Re-run `codex login`."
        )
    return access_token, account_id


_DEFAULT_INSTRUCTIONS = "You are a helpful assistant."


def _extract_system_text(content: Any) -> list[str]:
    """Pull plain text out of a Responses-API system message ``content`` field.

    LangChain emits system content either as a bare string or as a list of
    typed parts (``{"type": "text"/"input_text", "text": "..."}``). The
    chatgpt.com endpoint wants a single ``instructions`` string, so this
    flattens both shapes.
    """
    if isinstance(content, str):
        return [content] if content else []
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, dict):
                text = part.get("text") or part.get("input_text")
                if text:
                    parts.append(text)
            elif isinstance(part, str) and part:
                parts.append(part)
        return parts
    return []


class CodexOAuthChat(NormalizedChatOpenAI):
    """ChatOpenAI variant that enforces the ChatGPT-Codex endpoint contract.

    The endpoint differs from the regular OpenAI Responses API in four
    ways enforced here on every outbound request:

      * top-level ``instructions`` field is required; system messages in
        the ``input`` array are not honoured. We promote any
        ``role=system`` items out of ``input`` into ``instructions``,
        and supply a default when no system message is present.
      * ``store`` is forced to ``False`` (endpoint rejects ``True``)
      * ``stream`` is forced to ``True`` (endpoint rejects non-streaming)
      * ``max_output_tokens`` and ``max_tokens`` are stripped (unsupported)

    Doing this in ``_get_request_payload`` rather than at construction
    time means user code that passes ``max_tokens`` or a SystemMessage
    won't crash -- the request shape is silently corrected to match
    what the endpoint accepts, so callers can target this provider with
    the same LangChain code they'd write for regular OpenAI.
    """

    def _get_request_payload(self, input_, *, stop=None, **kwargs):
        payload = super()._get_request_payload(input_, stop=stop, **kwargs)

        for key in _STRIPPED_REQUEST_KEYS:
            payload.pop(key, None)
        payload["store"] = False
        payload["stream"] = True

        instructions_parts: list[str] = []
        existing_instructions = payload.get("instructions")
        if isinstance(existing_instructions, str) and existing_instructions:
            instructions_parts.append(existing_instructions)

        remaining_items = []
        for item in payload.get("input") or []:
            if isinstance(item, dict) and item.get("role") == "system":
                instructions_parts.extend(_extract_system_text(item.get("content")))
            else:
                remaining_items.append(item)

        payload["input"] = remaining_items
        payload["instructions"] = (
            "\n\n".join(instructions_parts) if instructions_parts else _DEFAULT_INSTRUCTIONS
        )
        return payload


class CodexOAuthClient(BaseLLMClient):
    """LangChain-compatible Codex OAuth client.

    Reads OAuth credentials from ``~/.codex/auth.json`` (override via the
    ``auth_file`` kwarg or ``CODEX_AUTH_FILE`` env var) and routes
    requests through ``chatgpt.com/backend-api/codex/responses`` using
    LangChain's Responses-API path. Tool calling and message-list
    handling come for free from ``NormalizedChatOpenAI``.

    Token refresh: the access token lives ~10 days. The Codex CLI
    auto-refreshes whenever invoked, so we read ``auth.json`` fresh at
    each ``get_llm()`` call. If the token expires while a graph is
    running, the request will 401; the next ``get_llm()`` call will pick
    up a fresh token. A future enhancement could refresh inline using
    the stored refresh_token.
    """

    provider = "codex-oauth"

    # Model slugs the ChatGPT-plan Codex endpoint accepts. Standard API
    # model names (gpt-4o, gpt-5, o3, ...) are explicitly rejected with
    # "not supported when using Codex with a ChatGPT account".
    KNOWN_MODELS = frozenset(
        {
            "gpt-5.5",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.3-codex",
            "gpt-5.3-codex-spark",
            "gpt-5.2",
            "codex-auto-review",
        }
    )

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, base_url, **kwargs)

    def _resolve_auth_file(self) -> Path:
        from_kwarg = self.kwargs.get("auth_file")
        if from_kwarg:
            return Path(str(from_kwarg)).expanduser()
        from_env = os.environ.get("CODEX_AUTH_FILE")
        if from_env:
            return Path(from_env).expanduser()
        return DEFAULT_AUTH_FILE

    def get_llm(self) -> CodexOAuthChat:
        access_token, account_id = _read_codex_auth(self._resolve_auth_file())
        llm_kwargs: dict[str, Any] = {
            "model": self.model,
            "base_url": self.base_url or CODEX_RESPONSES_BASE_URL,
            "api_key": access_token,
            "default_headers": {"chatgpt-account-id": account_id},
            "use_responses_api": True,
            "streaming": True,
        }
        # Forward a small set of generic kwargs from user config. The
        # endpoint rejects max_*_tokens so we deliberately don't forward
        # those even if a caller sets them; they're stripped in
        # ``CodexOAuthChat._get_request_payload`` for defense in depth.
        for key in ("timeout", "max_retries", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        return CodexOAuthChat(**llm_kwargs)

    def validate_model(self) -> bool:
        return self.model in self.KNOWN_MODELS
