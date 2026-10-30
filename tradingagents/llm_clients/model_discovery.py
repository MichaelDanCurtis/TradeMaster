"""Best-effort model-list discovery for the provider dropdown UIs.

The Settings page wants to populate per-agent model pickers with the
actual models a given provider exposes. This module knows how to ask
each provider kind for that list:

* ``codex-oauth`` -- read ``~/.codex/models_cache.json`` (the Codex CLI
  already populates this and refreshes it on use). Avoids a network
  call entirely.
* OpenAI-compatible (``openai``, ``openai-compatible``, etc.) -- hit
  ``GET {base_url}/models`` with whatever API key the caller supplies.
  This is the standard OpenAI listing format; OpenRouter, LM Studio,
  GLM, Kimi, and most local servers implement it.
* ``anthropic`` -- Anthropic's standard API does NOT expose a public
  ``/v1/models`` endpoint, so we return a curated static list.

A discovery failure (network error, 401, unsupported endpoint) is
returned as an empty list with a ``source`` of ``"unavailable"`` so
the UI can fall back to a free-text input instead of crashing.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import httpx


CODEX_MODELS_CACHE_PATH = Path.home() / ".codex" / "models_cache.json"

# Anthropic's standard API has no public /v1/models endpoint as of the
# 4.x model family, so we publish a static list of the production
# models the SDK accepts. Keep this in sync with the SDK's known set;
# user-defined Anthropic-compatible providers will get the same list
# (they can override per-role with free-text if their gateway exposes
# something custom).
ANTHROPIC_STATIC_MODELS: tuple[str, ...] = (
    "claude-opus-4-7",
    "claude-sonnet-4-6",
    "claude-haiku-4-5",
)

# Request timeout in seconds for /v1/models probes. Kept tight because
# this is called inline from a settings-page render; an unresponsive
# provider must not hang the UI.
_DISCOVERY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class ModelDiscoveryResult:
    """What we found and where it came from."""

    models: list[str]
    source: str  # one of: "codex_cache", "api", "static", "unavailable"
    detail: str | None = None


def discover_models(
    *,
    provider: str,
    base_url: str | None,
    api_key: str | None,
    default_headers: dict[str, str] | None = None,
) -> ModelDiscoveryResult:
    """Resolve the model list for a provider's settings dropdown."""
    provider_lower = (provider or "").lower()

    if provider_lower == "codex-oauth":
        return _discover_codex_models()

    if provider_lower == "anthropic":
        return ModelDiscoveryResult(
            models=list(ANTHROPIC_STATIC_MODELS),
            source="static",
        )

    # Everything else: best-effort OpenAI-compatible /v1/models probe.
    if not base_url:
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail="provider has no base_url configured",
        )

    return _discover_openai_compatible_models(
        base_url=base_url,
        api_key=api_key,
        default_headers=default_headers or {},
    )


def _discover_codex_models() -> ModelDiscoveryResult:
    """Read the Codex CLI's model cache. Avoids the network entirely."""
    cache_path = Path(os.environ.get("CODEX_MODELS_CACHE", str(CODEX_MODELS_CACHE_PATH)))
    if not cache_path.exists():
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"codex models_cache.json not found at {cache_path}",
        )
    try:
        payload = json.loads(cache_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"could not parse codex models_cache.json: {exc}",
        )
    return ModelDiscoveryResult(
        models=_extract_codex_slugs(payload.get("models") or []),
        source="codex_cache",
    )


def _extract_codex_slugs(raw_models: Iterable[Any]) -> list[str]:
    slugs: list[str] = []
    for entry in raw_models:
        if isinstance(entry, dict):
            slug = entry.get("slug") or entry.get("id") or entry.get("name")
            if isinstance(slug, str) and slug:
                slugs.append(slug)
        elif isinstance(entry, str) and entry:
            slugs.append(entry)
    return slugs


def _discover_openai_compatible_models(
    *,
    base_url: str,
    api_key: str | None,
    default_headers: dict[str, str],
) -> ModelDiscoveryResult:
    """GET {base_url}/models -- the OpenAI catalog endpoint shape."""
    url = base_url.rstrip("/") + "/models"
    headers: dict[str, str] = {"Accept": "application/json", **default_headers}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = httpx.get(url, headers=headers, timeout=_DISCOVERY_TIMEOUT_SECONDS)
    except httpx.HTTPError as exc:
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"network error reaching {url}: {exc}",
        )

    if response.status_code != 200:
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"{url} returned HTTP {response.status_code}",
        )

    try:
        body = response.json()
    except ValueError as exc:
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"{url} returned non-JSON: {exc}",
        )

    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return ModelDiscoveryResult(
            models=[],
            source="unavailable",
            detail=f"{url} response missing data[] array",
        )

    models = [
        item.get("id") for item in data
        if isinstance(item, dict) and isinstance(item.get("id"), str) and item.get("id")
    ]
    return ModelDiscoveryResult(models=models, source="api")
