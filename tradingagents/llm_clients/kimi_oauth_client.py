"""LangChain ChatModel that talks to Kimi for Coding (Moonshot OAuth).

Kimi for Coding exposes an *Anthropic Messages*-shaped endpoint gated behind
the Kimi OAuth device flow rather than a static API key:

  1. ``cli-proxy-api-plus -kimi-login`` saves an OAuth session at
     ``~/.ccs/cliproxy/auth/kimi-<millis>.json`` containing an ``access_token``
     (JWT), a rotating ``refresh_token`` (JWT, ~30 d), ``device_id`` and
     metadata. TradeMaster always selects the *newest* ``kimi-*.json`` by the
     numeric timestamp suffix at runtime -- the login tool writes a new file
     per session.
  2. Completions are POSTed to ``https://api.kimi.com/coding/v1/messages``
     with ``Authorization: Bearer <access_token>`` and
     ``anthropic-version: 2023-06-01``. Request/response bodies are Anthropic
     Messages format. ``kimi-k2-thinking`` is a reasoning model: the response
     contains a ``thinking`` content block *before* the ``text`` block(s);
     only the text blocks form the reply.
  3. Access tokens expire (login-issued ~10 h; refresh-issued ~15 min). They
     are refreshed at ``https://auth.kimi.com/api/oauth/token`` (endpoint
     recovered from the cli-proxy-api-plus binary, ``kimi/token.go``) with a
     form-encoded ``grant_type=refresh_token`` request. The refresh token
     ROTATES on every refresh, so the updated pair is written back to the
     auth file atomically -- cliproxy and TradeMaster share the credential.

The bearer is cached module-level (per auth directory) behind a lock; expiry
is read from the JWT ``exp`` claim (decoded locally, unverified). A 401 from
the completions endpoint forces exactly one refresh + retry. If the refresh
endpoint rejects the session, we degrade gracefully: keep using the current
access token until its expiry, then raise :class:`KimiOAuthAuthError` telling
the user to re-run the Kimi login.
"""

from __future__ import annotations

import base64
import glob
import json
import os
import tempfile
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Optional

import requests
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.utils.function_calling import convert_to_openai_tool

from .base_client import BaseLLMClient

# Directory the cliproxy Kimi login writes auth sessions into.
DEFAULT_AUTH_DIR = Path.home() / ".ccs" / "cliproxy" / "auth"

# Verified live contract (probed this session).
KIMI_MESSAGES_URL = "https://api.kimi.com/coding/v1/messages"
KIMI_ANTHROPIC_VERSION = "2023-06-01"

# Refresh endpoint recovered from cli-proxy-api-plus (internal/auth/kimi/token.go)
# and verified live: form-encoded grant_type=refresh_token + refresh_token +
# client_id -> 200 {access_token, refresh_token, expires_in, token_type, scope}.
KIMI_TOKEN_REFRESH_URL = "https://auth.kimi.com/api/oauth/token"
KIMI_CLIENT_ID = "17e5f671-d194-4dfb-9706-5516cb48c098"

# Refresh when the access token is within this many seconds of its JWT exp.
_TOKEN_REFRESH_MARGIN_S = 60

# Anthropic Messages requires max_tokens; kimi-k2-thinking spends tokens on
# its thinking block before the text reply, so leave generous headroom.
_DEFAULT_MAX_TOKENS = 16384

_RELOGIN_HINT = (
    "Re-run the Kimi login to mint a fresh session: "
    "~/.ccs/cliproxy/bin/plus/cli-proxy-api-plus -kimi-login "
    "-config ~/.ccs/cliproxy/config.yaml"
)

KNOWN_KIMI_MODELS = frozenset({"kimi-k2-thinking"})


class KimiOAuthAuthError(RuntimeError):
    """Raised when the Kimi OAuth session is missing or unusable."""


def _newest_auth_file(auth_dir: Path) -> Path:
    """Return the newest ``kimi-*.json`` in ``auth_dir`` by timestamp suffix."""
    candidates = []
    for path in glob.glob(str(auth_dir / "kimi-*.json")):
        stem = Path(path).stem  # "kimi-<millis>"
        suffix = stem.split("-", 1)[-1]
        try:
            candidates.append((int(suffix), Path(path)))
        except ValueError:
            continue
    if not candidates:
        raise KimiOAuthAuthError(
            f"No kimi-*.json auth session found in {auth_dir}. {_RELOGIN_HINT}"
        )
    return max(candidates)[1]


def _jwt_exp(token: str) -> int:
    """Decode the ``exp`` claim from a JWT locally (no signature check)."""
    try:
        payload_b64 = token.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload_b64))
        return int(claims["exp"])
    except (IndexError, KeyError, ValueError, json.JSONDecodeError) as exc:
        raise KimiOAuthAuthError(
            f"Kimi access token is not a decodable JWT: {exc}. {_RELOGIN_HINT}"
        ) from exc


class _KimiTokenCache:
    """Thread-safe access-token cache for one Kimi auth directory.

    ``get()`` returns a bearer that is at least ``_TOKEN_REFRESH_MARGIN_S``
    from its JWT expiry, refreshing (and atomically persisting the rotated
    pair) when needed. ``force_refresh()`` is used after a 401 to retry once.
    If the refresh endpoint rejects the session we degrade gracefully: the
    current access token is used until it actually expires, then a clear
    :class:`KimiOAuthAuthError` directs the user to re-login.
    """

    def __init__(self, auth_dir: Path) -> None:
        self._auth_dir = auth_dir
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._exp: int = 0
        self._auth_path: Optional[Path] = None

    def get(self) -> str:
        with self._lock:
            if self._needs_refresh():
                self._refresh_locked(force=False)
            return self._access_token  # type: ignore[return-value]

    def force_refresh(self) -> str:
        with self._lock:
            self._refresh_locked(force=True)
            return self._access_token  # type: ignore[return-value]

    def _needs_refresh(self) -> bool:
        return (
            self._access_token is None
            or time.time() >= (self._exp - _TOKEN_REFRESH_MARGIN_S)
        )

    def _refresh_locked(self, *, force: bool) -> None:
        # Always re-select the newest auth file: a fresh -kimi-login (or a
        # cliproxy-side refresh) may have superseded what we cached.
        auth_path = _newest_auth_file(self._auth_dir)
        try:
            auth = json.loads(auth_path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise KimiOAuthAuthError(
                f"Kimi auth file {auth_path} is unreadable: {exc}. {_RELOGIN_HINT}"
            ) from exc

        access_token = auth.get("access_token")
        refresh_token = auth.get("refresh_token")
        if not access_token:
            raise KimiOAuthAuthError(
                f"Kimi auth file {auth_path} has no 'access_token'. {_RELOGIN_HINT}"
            )

        exp = _jwt_exp(access_token)
        file_token_fresh = time.time() < (exp - _TOKEN_REFRESH_MARGIN_S)
        if file_token_fresh and not (force and access_token == self._access_token):
            # The on-disk token is usable (and, on a forced 401 retry, is a
            # different token than the one that just failed).
            self._access_token, self._exp, self._auth_path = access_token, exp, auth_path
            return

        if not refresh_token:
            raise KimiOAuthAuthError(
                f"Kimi access token expired and {auth_path} has no "
                f"'refresh_token'. {_RELOGIN_HINT}"
            )

        refreshed = self._request_refresh(refresh_token)
        if refreshed is None:
            # Graceful degrade: refresh endpoint unusable. Ride the current
            # access token until it truly expires, then fail with guidance.
            if time.time() < exp:
                self._access_token, self._exp, self._auth_path = access_token, exp, auth_path
                return
            raise KimiOAuthAuthError(
                "Kimi access token is expired and the refresh request was "
                f"rejected. {_RELOGIN_HINT}"
            )

        new_access = refreshed["access_token"]
        self._write_back(auth_path, auth, refreshed)
        self._access_token = new_access
        self._exp = _jwt_exp(new_access)
        self._auth_path = auth_path

    @staticmethod
    def _request_refresh(refresh_token: str) -> Optional[dict[str, Any]]:
        """POST the refresh grant; return the token payload or None on failure."""
        try:
            resp = requests.post(
                KIMI_TOKEN_REFRESH_URL,
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": KIMI_CLIENT_ID,
                },
                timeout=30,
            )
        except requests.RequestException:
            return None
        if resp.status_code != 200:
            return None
        try:
            data = resp.json()
        except (json.JSONDecodeError, ValueError):
            return None
        if not data.get("access_token"):
            return None
        return data

    @staticmethod
    def _write_back(auth_path: Path, auth: dict[str, Any], refreshed: dict[str, Any]) -> None:
        """Atomically persist the rotated token pair in the original shape."""
        updated = dict(auth)
        updated["access_token"] = refreshed["access_token"]
        if refreshed.get("refresh_token"):
            updated["refresh_token"] = refreshed["refresh_token"]
        if refreshed.get("token_type"):
            updated["token_type"] = refreshed["token_type"]
        if refreshed.get("scope"):
            updated["scope"] = refreshed["scope"]
        try:
            expires_in = int(refreshed.get("expires_in") or 900)
        except (TypeError, ValueError):
            expires_in = 900
        updated["expired"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in)
        )
        updated["timestamp"] = int(time.time() * 1000)
        try:
            fd, tmp = tempfile.mkstemp(
                dir=str(auth_path.parent), prefix=".kimi-write-"
            )
            with os.fdopen(fd, "w") as fh:
                json.dump(updated, fh, indent=2)
            os.replace(tmp, auth_path)
        except OSError:
            # Persisting is best-effort; the in-memory pair remains valid for
            # this process even if the disk write-back fails.
            pass


# One cache per auth directory, shared across client instances so concurrent
# role-LLM construction reuses (and never races) a single token refresh.
_TOKEN_CACHES: dict[str, _KimiTokenCache] = {}
_TOKEN_CACHES_LOCK = threading.Lock()


def _cache_for(auth_dir: Path) -> _KimiTokenCache:
    key = str(auth_dir)
    with _TOKEN_CACHES_LOCK:
        cache = _TOKEN_CACHES.get(key)
        if cache is None:
            cache = _KimiTokenCache(auth_dir)
            _TOKEN_CACHES[key] = cache
        return cache


def _block_text(block: Any) -> str:
    """Extract plain text from a message content block (dict or str)."""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        if block.get("type") in (None, "text"):
            return str(block.get("text", "") or "")
    return ""


def _message_text(message: BaseMessage) -> str:
    """Flatten a LangChain message's content to plain text."""
    content = message.content
    if isinstance(content, list):
        return "\n".join(t for t in (_block_text(b) for b in content) if t)
    return str(content or "")


def _to_anthropic_messages(
    messages: list[BaseMessage],
) -> tuple[Optional[str], list[dict[str, Any]]]:
    """Translate LangChain messages into Anthropic ``(system, messages)``.

    System messages are lifted into the top-level ``system`` string. Turns are
    built as content-block lists so tool traffic survives the round trip:

    - ai turns replay any captured ``thinking`` blocks first (reasoning models
      require them ahead of ``tool_use`` on the next request), then text, then
      ``tool_use`` blocks derived from ``AIMessage.tool_calls``;
    - tool results become user-turn ``tool_result`` blocks keyed by
      ``tool_call_id``;
    - consecutive same-role turns are merged because the Anthropic Messages
      format requires strict role alternation.
    """
    system_parts: list[str] = []
    turns: list[dict[str, Any]] = []

    def _append(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": blocks})

    for message in messages:
        role = getattr(message, "type", "human")
        if role == "system":
            text = _message_text(message)
            if text:
                system_parts.append(text)
            continue
        if role == "tool":
            _append(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": str(getattr(message, "tool_call_id", "") or ""),
                        "content": _message_text(message),
                    }
                ],
            )
            continue
        if role == "ai":
            blocks: list[dict[str, Any]] = []
            for thinking in (message.additional_kwargs or {}).get(
                "thinking_blocks", []
            ):
                if isinstance(thinking, dict):
                    blocks.append(thinking)
            text = _message_text(message)
            if text:
                blocks.append({"type": "text", "text": text})
            for tool_call in getattr(message, "tool_calls", None) or []:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": str(tool_call.get("id") or ""),
                        "name": str(tool_call.get("name") or ""),
                        "input": tool_call.get("args") or {},
                    }
                )
            _append("assistant", blocks)
            continue
        text = _message_text(message)
        if text:
            _append("user", [{"type": "text", "text": text}])

    if turns and turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": [{"type": "text", "text": "(continue)"}]})
    if not turns:
        turns.append({"role": "user", "content": [{"type": "text", "text": "(empty)"}]})
    system = "\n\n".join(system_parts) if system_parts else None
    return system, turns


class KimiOAuthChat(BaseChatModel):
    """Anthropic-Messages chat model for Kimi for Coding.

    Sends the Bearer from the shared token cache per request; on a 401 it
    forces exactly one refresh and retries once (covers a token expiring
    mid-graph). The reply is assembled from the response's ``text`` content
    blocks only -- kimi-k2-thinking's leading ``thinking`` block is skipped.
    """

    model: str = "kimi-k2-thinking"
    max_tokens: int = _DEFAULT_MAX_TOKENS
    temperature: Optional[float] = None
    timeout: int = 300
    token_cache: Any = None

    @property
    def _llm_type(self) -> str:
        return "kimi-oauth"

    @property
    def _identifying_params(self) -> dict[str, Any]:
        return {"model": self.model, "endpoint": KIMI_MESSAGES_URL}

    def bind_tools(
        self,
        tools: Sequence[Any],
        *,
        tool_choice: Any = None,
        **kwargs: Any,
    ) -> Runnable[Any, BaseMessage]:
        """Bind tools in Anthropic ``input_schema`` format.

        Accepts the same tool shapes LangChain's ``convert_to_openai_tool``
        does (BaseTool, pydantic model, function, dict); dicts already in
        Anthropic shape pass through untouched.
        """
        formatted: list[dict[str, Any]] = []
        for tool in tools:
            if isinstance(tool, dict) and "input_schema" in tool:
                formatted.append(tool)
                continue
            fn = convert_to_openai_tool(tool)["function"]
            formatted.append(
                {
                    "name": fn["name"],
                    "description": fn.get("description", ""),
                    "input_schema": fn.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
        bind_kwargs = dict(kwargs)
        if tool_choice in ("any", "required"):
            bind_kwargs["tool_choice"] = {"type": "any"}
        elif isinstance(tool_choice, dict):
            bind_kwargs["tool_choice"] = tool_choice
        elif isinstance(tool_choice, str) and tool_choice not in ("auto", "none"):
            bind_kwargs["tool_choice"] = {"type": "tool", "name": tool_choice}
        return self.bind(tools=formatted, **bind_kwargs)

    def with_structured_output(self, schema: Any, **kwargs: Any) -> Any:
        """Decline structured output so callers use their free-text fallback.

        ``BaseChatModel``'s default implementation would route through
        ``bind_tools`` with a *forced* ``tool_choice`` -- Kimi rejects that
        outright for thinking models (HTTP 400: "tool_choice 'required' is
        incompatible with thinking enabled"), costing a wasted request before
        callers retry. Raising here lets graph nodes take their proven
        bind-time free-text fallback instead.
        """
        raise NotImplementedError(
            "kimi-k2-thinking does not support forced structured output "
            "(tool_choice is incompatible with thinking); use free-text "
            "generation instead."
        )

    def _post_messages(self, payload: dict[str, Any]) -> dict[str, Any]:
        cache: _KimiTokenCache = self.token_cache

        def _send(bearer: str) -> requests.Response:
            return requests.post(
                KIMI_MESSAGES_URL,
                headers={
                    "Authorization": f"Bearer {bearer}",
                    "Content-Type": "application/json",
                    "anthropic-version": KIMI_ANTHROPIC_VERSION,
                },
                json=payload,
                timeout=self.timeout,
            )

        try:
            resp = _send(cache.get())
            if resp.status_code == 401:
                # Retry exactly once with a force-refreshed bearer.
                resp = _send(cache.force_refresh())
        except requests.RequestException as exc:
            raise RuntimeError(f"Kimi completion request failed: {exc}") from exc

        if resp.status_code == 401:
            raise KimiOAuthAuthError(
                f"Kimi rejected the access token even after refresh "
                f"(HTTP 401): {resp.text[:300]}. {_RELOGIN_HINT}"
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"Kimi completion failed (HTTP {resp.status_code}): {resp.text[:500]}"
            )
        try:
            return resp.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise RuntimeError(
                f"Kimi returned non-JSON: {resp.text[:300]}"
            ) from exc

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> ChatResult:
        system, turns = _to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": kwargs.get("max_tokens", self.max_tokens),
            "messages": turns,
        }
        if system:
            payload["system"] = system
        if self.temperature is not None:
            payload["temperature"] = self.temperature
        if stop:
            payload["stop_sequences"] = list(stop)
        tools = kwargs.get("tools")
        if tools:
            payload["tools"] = tools
        tool_choice = kwargs.get("tool_choice")
        if tool_choice:
            payload["tool_choice"] = tool_choice

        data = self._post_messages(payload)

        # kimi-k2-thinking emits a "thinking" block before text/tool_use
        # blocks. Text blocks form the reply; tool_use blocks become LangChain
        # tool calls; thinking blocks are preserved verbatim so the next turn
        # can replay them ahead of their tool_use (the endpoint requires it).
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        thinking_blocks: list[dict[str, Any]] = []
        for block in data.get("content", []):
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                block_text = str(block.get("text", "") or "")
                if block_text:
                    text_parts.append(block_text)
            elif block_type == "tool_use":
                raw_input = block.get("input")
                tool_calls.append(
                    {
                        "name": str(block.get("name") or ""),
                        "args": raw_input if isinstance(raw_input, dict) else {},
                        "id": str(block.get("id") or ""),
                        "type": "tool_call",
                    }
                )
            elif block_type == "thinking":
                thinking_blocks.append(block)

        usage = data.get("usage") or {}
        additional_kwargs: dict[str, Any] = {}
        if thinking_blocks:
            additional_kwargs["thinking_blocks"] = thinking_blocks
        message = AIMessage(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            additional_kwargs=additional_kwargs,
            response_metadata={
                "model": data.get("model", self.model),
                "stop_reason": data.get("stop_reason"),
                "usage": usage,
            },
        )
        return ChatResult(generations=[ChatGeneration(message=message)])


class KimiOAuthClient(BaseLLMClient):
    """LangChain-compatible Kimi for Coding (Moonshot OAuth) client.

    Resolves the newest ``kimi-*.json`` session under
    ``~/.ccs/cliproxy/auth`` (override via the ``auth_dir`` kwarg), keeps the
    bearer fresh through the shared token cache (JWT-exp check, refresh with
    rotation write-back, retry-once-on-401), and speaks Anthropic Messages to
    the verified ``api.kimi.com/coding/v1/messages`` endpoint.
    """

    provider = "kimi-oauth"

    KNOWN_MODELS = KNOWN_KIMI_MODELS

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, base_url, **kwargs)

    def _resolve_auth_dir(self) -> Path:
        from_kwarg = self.kwargs.get("auth_dir")
        if from_kwarg:
            return Path(str(from_kwarg)).expanduser()
        return DEFAULT_AUTH_DIR

    def get_llm(self) -> KimiOAuthChat:
        self.warn_if_unknown_model()
        cache = _cache_for(self._resolve_auth_dir())
        # Eagerly resolve once so construction fails loudly on a missing or
        # dead session rather than mid-graph.
        cache.get()

        llm_kwargs: dict[str, Any] = {
            "model": self.model or "kimi-k2-thinking",
            "token_cache": cache,
        }
        for key in ("timeout", "temperature", "max_tokens", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        return KimiOAuthChat(**llm_kwargs)

    def validate_model(self) -> bool:
        return self.model in self.KNOWN_MODELS
