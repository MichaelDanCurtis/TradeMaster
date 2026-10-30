"""LangChain ChatModel that talks to GitHub Copilot's OpenAI-compatible API.

GitHub Copilot exposes an OpenAI Chat Completions-shaped endpoint, but it is
gated behind a two-step OAuth flow rather than a static API key:

  1. A long-lived GitHub *user* token (``ghu_...``) is saved locally by the
     Copilot editor integrations. TradeMaster stores its own copy at
     ``~/.config/github-copilot/trademaster-oauth.json``. (Fallback source:
     ``~/.config/github-copilot/apps.json``, value keyed by
     ``github.com:<client_id>``.)
  2. That user token is exchanged at
     ``GET https://api.github.com/copilot_internal/v2/token`` for a
     short-lived (~25 min) Copilot *bearer* token plus the set of completion
     endpoints for the account. Business seats resolve to
     ``https://api.business.githubcopilot.com`` -- we always use the
     ``endpoints.api`` value returned by the exchange rather than guessing.

The bearer is cached (with its ``expires_at``) and re-exchanged when within
60 s of expiry. Completions are standard OpenAI Chat Completions, so most of
the heavy lifting (tool calling, structured output, content normalization)
comes for free from ``NormalizedChatOpenAI``.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Optional

import requests

from .base_client import BaseLLMClient
from .openai_client import NormalizedChatOpenAI


# Where TradeMaster stores its own copy of the GitHub user token.
DEFAULT_OAUTH_FILE = Path.home() / ".config" / "github-copilot" / "trademaster-oauth.json"
# Fallback: the file the Copilot editor plugins write.
APPS_FALLBACK_FILE = Path.home() / ".config" / "github-copilot" / "apps.json"

# The token-exchange endpoint. The completion base URL is *not* hard-coded --
# it comes back as ``endpoints.api`` from this exchange (Business seats use a
# different host than consumer seats).
COPILOT_TOKEN_EXCHANGE_URL = "https://api.github.com/copilot_internal/v2/token"

# Editor-identity headers Copilot expects on both the exchange and completion
# calls. Lifted verbatim from the verified live contract.
_COPILOT_EDITOR_VERSION = "vscode/1.95.0"
_COPILOT_USER_AGENT = "GitHubCopilot/1.155.0"
_COPILOT_PLUGIN_VERSION = "copilot-chat/0.22.0"
_COPILOT_INTEGRATION_ID = "vscode-chat"

# Re-exchange the bearer when it is within this many seconds of expiry.
_BEARER_REFRESH_MARGIN_S = 60

# Fictional default slugs that appear elsewhere in the repo but are NOT hosted
# by Copilot. We map these onto real Copilot models.
_FICTIONAL_QUICK_PREFIXES = ("gpt-5.4-mini", "gpt-5.5-mini")
_FICTIONAL_DEEP_PREFIXES = ("gpt-5.4", "gpt-5.5", "gpt-5.3", "gpt-5.2")

# Real Copilot fallbacks (verified working on this Business account).
_FALLBACK_QUICK_MODEL = "gpt-4o-mini"
_FALLBACK_DEEP_MODEL = "gpt-4o"

# Real model slugs we recognise (used only for validate_model warnings).
KNOWN_COPILOT_MODELS = frozenset(
    {
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4.1",
        "gpt-4.1-mini",
        "o1",
        "o1-mini",
        "o3-mini",
    }
)


class CopilotOAuthAuthError(RuntimeError):
    """Raised when the Copilot OAuth session is missing or unusable."""


def _read_github_user_token(oauth_file: Path) -> str:
    """Return the long-lived GitHub user token (``ghu_...``).

    Prefers ``oauth_file`` (TradeMaster's own copy); falls back to the
    Copilot editor plugins' ``apps.json``.
    """
    if oauth_file.exists():
        try:
            payload = json.loads(oauth_file.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CopilotOAuthAuthError(
                f"Copilot OAuth file at {oauth_file} is unreadable: {exc}"
            ) from exc
        token = payload.get("oauth_token")
        if token:
            return str(token)
        raise CopilotOAuthAuthError(
            f"Copilot OAuth file at {oauth_file} has no 'oauth_token' field."
        )

    # Fallback: ~/.config/github-copilot/apps.json keyed by github.com:<clientid>.
    if APPS_FALLBACK_FILE.exists():
        try:
            apps = json.loads(APPS_FALLBACK_FILE.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise CopilotOAuthAuthError(
                f"Copilot fallback file {APPS_FALLBACK_FILE} is unreadable: {exc}"
            ) from exc
        for key, value in apps.items():
            if isinstance(value, dict) and key.startswith("github.com:"):
                token = value.get("oauth_token")
                if token:
                    return str(token)
        raise CopilotOAuthAuthError(
            f"No github.com Copilot token found in fallback {APPS_FALLBACK_FILE}."
        )

    raise CopilotOAuthAuthError(
        f"GitHub Copilot OAuth token not found at {oauth_file} "
        f"(or fallback {APPS_FALLBACK_FILE}). Sign in to Copilot to create it."
    )


def _exchange_for_bearer(user_token: str) -> tuple[str, int, str]:
    """Exchange the GitHub user token for ``(bearer, expires_at, api_base)``."""
    headers = {
        "Authorization": f"token {user_token}",
        "User-Agent": _COPILOT_USER_AGENT,
        "Editor-Version": _COPILOT_EDITOR_VERSION,
        "Editor-Plugin-Version": _COPILOT_PLUGIN_VERSION,
    }
    try:
        resp = requests.get(COPILOT_TOKEN_EXCHANGE_URL, headers=headers, timeout=30)
    except requests.RequestException as exc:
        raise CopilotOAuthAuthError(
            f"Copilot token exchange request failed: {exc}"
        ) from exc

    if resp.status_code in (401, 403):
        raise CopilotOAuthAuthError(
            f"Copilot token exchange rejected the GitHub user token "
            f"(HTTP {resp.status_code}). The token may be expired or lack a "
            f"Copilot seat. Re-authenticate Copilot. Body: {resp.text[:300]}"
        )
    if resp.status_code != 200:
        raise CopilotOAuthAuthError(
            f"Copilot token exchange failed (HTTP {resp.status_code}): "
            f"{resp.text[:300]}"
        )

    try:
        data = resp.json()
    except json.JSONDecodeError as exc:
        raise CopilotOAuthAuthError(
            f"Copilot token exchange returned non-JSON: {resp.text[:300]}"
        ) from exc

    bearer = data.get("token")
    expires_at = data.get("expires_at")
    endpoints = data.get("endpoints") or {}
    api_base = endpoints.get("api")
    if not bearer or not api_base:
        raise CopilotOAuthAuthError(
            "Copilot token exchange response missing 'token' or "
            f"'endpoints.api': {json.dumps(data)[:300]}"
        )
    # expires_at is a unix int; default to a conservative 15-min lifetime if absent.
    expires_at_int = int(expires_at) if expires_at is not None else int(time.time()) + 900
    return str(bearer), expires_at_int, str(api_base)


def map_copilot_model(model: str) -> str:
    """Map a configured model slug onto a real Copilot model.

    Honors any explicitly-real slug (gpt-4o, gpt-4o-mini, o1, ...). Fictional
    gpt-5.4* / gpt-5.5* slugs that appear as defaults elsewhere in the repo are
    remapped: ``*-mini`` -> gpt-4o-mini (quick), otherwise -> gpt-4o (deep).
    """
    if not model:
        return _FALLBACK_DEEP_MODEL
    lowered = model.lower()
    if lowered.startswith(_FICTIONAL_QUICK_PREFIXES):
        return _FALLBACK_QUICK_MODEL
    if lowered.startswith(_FICTIONAL_DEEP_PREFIXES):
        # A "-mini" variant of a deep prefix should still go quick.
        if lowered.endswith("-mini"):
            return _FALLBACK_QUICK_MODEL
        return _FALLBACK_DEEP_MODEL
    # "copilot-default" / other placeholders -> deep model.
    if lowered in ("copilot-default", "default"):
        return _FALLBACK_DEEP_MODEL
    return model


class _CopilotBearerCache:
    """Thread-safe cache of the short-lived Copilot bearer + api base.

    Shared via the client so the parallel-analyst path doesn't trigger one
    exchange per analyst. ``get()`` re-exchanges when within the refresh margin
    of expiry; ``force_refresh()`` is used after a 401 to retry once.
    """

    def __init__(self, oauth_file: Path) -> None:
        self._oauth_file = oauth_file
        self._lock = threading.Lock()
        self._bearer: Optional[str] = None
        self._expires_at: int = 0
        self._api_base: Optional[str] = None

    def _needs_refresh(self) -> bool:
        return (
            self._bearer is None
            or self._api_base is None
            or time.time() >= (self._expires_at - _BEARER_REFRESH_MARGIN_S)
        )

    def get(self) -> tuple[str, str]:
        """Return ``(bearer, api_base)``, exchanging/refreshing as needed."""
        with self._lock:
            if self._needs_refresh():
                self._refresh_locked()
            return self._bearer, self._api_base  # type: ignore[return-value]

    def force_refresh(self) -> tuple[str, str]:
        """Force a re-exchange (used after a 401) and return the fresh pair."""
        with self._lock:
            self._refresh_locked()
            return self._bearer, self._api_base  # type: ignore[return-value]

    def _refresh_locked(self) -> None:
        user_token = _read_github_user_token(self._oauth_file)
        bearer, expires_at, api_base = _exchange_for_bearer(user_token)
        self._bearer = bearer
        self._expires_at = expires_at
        self._api_base = api_base


# One cache per oauth-file path, shared across client instances so concurrent
# role-LLM construction reuses a single bearer.
_BEARER_CACHES: dict[str, _CopilotBearerCache] = {}
_BEARER_CACHES_LOCK = threading.Lock()


def _cache_for(oauth_file: Path) -> _CopilotBearerCache:
    key = str(oauth_file)
    with _BEARER_CACHES_LOCK:
        cache = _BEARER_CACHES.get(key)
        if cache is None:
            cache = _CopilotBearerCache(oauth_file)
            _BEARER_CACHES[key] = cache
        return cache


class CopilotOAuthChat(NormalizedChatOpenAI):
    """ChatOpenAI variant that refreshes the Copilot bearer per request.

    The bearer is short-lived, so we resolve it from the shared cache inside
    ``_get_request_payload`` (updating ``api_key`` + ``base_url`` on the bound
    OpenAI client). On a 401 from Copilot we force exactly one re-exchange and
    retry the request once -- this covers the case where a cached bearer
    expires mid-graph.
    """

    # Pydantic-friendly: these are set via object.__setattr__ in __init__.
    _bearer_cache: Any = None

    def __init__(self, *args: Any, bearer_cache: _CopilotBearerCache, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        object.__setattr__(self, "_bearer_cache", bearer_cache)

    def _apply_bearer(self, bearer: str, api_base: str) -> None:
        # Update the underlying sync + async OpenAI SDK clients in place so the
        # next request uses the fresh bearer/host.
        self.openai_api_key = bearer
        self.openai_api_base = api_base
        for attr in ("client", "async_client", "root_client", "root_async_client"):
            sdk = getattr(self, attr, None)
            if sdk is not None:
                try:
                    sdk.api_key = bearer
                    sdk.base_url = api_base if api_base.endswith("/") else api_base + "/"
                except Exception:  # pragma: no cover - defensive
                    pass

    def _refresh_before_request(self, *, force: bool = False) -> None:
        cache = self._bearer_cache
        bearer, api_base = cache.force_refresh() if force else cache.get()
        self._apply_bearer(bearer, api_base)

    def invoke(self, input, config=None, **kwargs):
        self._refresh_before_request()
        try:
            return super().invoke(input, config, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if _is_auth_error(exc):
                self._refresh_before_request(force=True)
                return super().invoke(input, config, **kwargs)
            raise


def _is_auth_error(exc: Exception) -> bool:
    """Detect a Copilot bearer 401 from a raised OpenAI SDK error."""
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    if status == 401:
        return True
    text = str(exc).lower()
    return "401" in text and ("unauth" in text or "token" in text or "expired" in text)


class CopilotOAuthClient(BaseLLMClient):
    """LangChain-compatible GitHub Copilot OAuth client.

    Resolves the GitHub user token from
    ``~/.config/github-copilot/trademaster-oauth.json`` (override via the
    ``oauth_file`` kwarg), exchanges it for a short-lived Copilot bearer
    (cached + auto-refreshed), and routes OpenAI Chat Completions to the
    account's ``endpoints.api`` (Business -> ``api.business.githubcopilot.com``).

    Model names are mapped through :func:`map_copilot_model` so the repo's
    fictional gpt-5.4* defaults fall back to real Copilot models, while an
    explicitly-real slug (gpt-4o, gpt-4o-mini, o1, ...) is honored as-is.
    """

    provider = "github-copilot-oauth"

    KNOWN_MODELS = KNOWN_COPILOT_MODELS

    def __init__(
        self,
        model: str,
        base_url: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(model, base_url, **kwargs)

    def _resolve_oauth_file(self) -> Path:
        from_kwarg = self.kwargs.get("oauth_file")
        if from_kwarg:
            return Path(str(from_kwarg)).expanduser()
        return DEFAULT_OAUTH_FILE

    def get_llm(self) -> CopilotOAuthChat:
        oauth_file = self._resolve_oauth_file()
        cache = _cache_for(oauth_file)
        # Eagerly exchange once so construction fails loudly on a bad token and
        # so the bound SDK client points at the correct Business host.
        bearer, api_base = cache.get()
        mapped_model = map_copilot_model(self.model)

        llm_kwargs: dict[str, Any] = {
            "model": mapped_model,
            "base_url": self.base_url or api_base,
            "api_key": bearer,
            "default_headers": {
                "Copilot-Integration-Id": _COPILOT_INTEGRATION_ID,
                "Editor-Version": _COPILOT_EDITOR_VERSION,
                "User-Agent": _COPILOT_USER_AGENT,
            },
            "bearer_cache": cache,
        }
        # Forward a small set of generic kwargs from user config.
        for key in ("timeout", "max_retries", "temperature", "callbacks"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]
        return CopilotOAuthChat(**llm_kwargs)

    def validate_model(self) -> bool:
        # The real (post-mapping) model is what actually hits Copilot.
        return map_copilot_model(self.model) in self.KNOWN_MODELS
