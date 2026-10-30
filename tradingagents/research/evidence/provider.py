"""Configured provider resolution and a tool-free, non-retrying SDK call."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_UP
from urllib.parse import urlsplit

from tradingagents.graph.role_models import resolve_role_model
from tradingagents.research.contracts import ExtractionPolicy, ModelRevision, canonical_json, content_hash
from tradingagents.research.evidence.extraction import Completion, SYSTEM_PROMPT, prompt_hash, schema_hash
from tradingagents.research.evidence.schema import guidance_schema
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.secrets import EnvSecretStore, MacKeychainSecretStore

SUPPORTED = {"openai", "openai-compatible", "anthropic", "xai", "deepseek", "qwen", "glm", "ollama", "openrouter", "codex-oauth"}


@dataclass(frozen=True)
class ProviderBinding:
    provider_id: str
    protocol: str
    model_id: str
    base_url: str | None
    config_hash: str
    secret_ref: str | None
    auth_required: bool
    codex_binary: str | None = None
    codex_home: str | None = None

    def credential(self) -> str:
        if self.secret_ref:
            store = EnvSecretStore() if self.secret_ref.startswith("env:") else MacKeychainSecretStore()
            try:
                return store.get_secret(self.secret_ref)
            except Exception:
                raise ValueError("Configured research credential is unavailable") from None
        if self.auth_required:
            raise ValueError("Configured research provider needs a secret reference")
        return "local-research-no-auth"


def resolve_provider(repo: UiRepository, role: str = "research_extractor") -> ProviderBinding:
    if role not in {"research_designer", "research_extractor"}:
        raise ValueError("Unknown strategy research role")
    assignments = {a.role_key: a.provider_id for a in repo.list_provider_role_assignments()}
    provider_id = assignments.get(role) or assignments.get("research_llm")
    if provider_id is None:
        raise ValueError("No research provider is assigned")
    provider = repo.get_provider_config(provider_id)
    if provider.role != "llm" or not provider.enabled:
        raise ValueError("Research role requires an enabled LLM provider")
    if provider.config.get("developer_mode") and not repo.get_developer_mode_enabled():
        raise ValueError("Selected provider requires the existing developer-mode setting")
    protocol = str(provider.config.get("provider") or "openai").lower()
    runtime = None
    codex_binary = codex_home = None
    if protocol == "codex-oauth":
        from tradingagents.research.evidence.codex import runtime_paths
        codex_binary, codex_home, runtime = runtime_paths(provider.config)
        protocol = "codex-app-server"
    if protocol not in SUPPORTED and protocol != "codex-app-server":
        raise ValueError(f"Provider protocol {protocol!r} has no verified bounded extraction adapter; desktop OAuth bridges are not substituted")
    base_url = str(provider.config["base_url"]) if provider.config.get("base_url") else None
    if base_url:
        parsed = urlsplit(base_url)
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Provider endpoint must be a plain HTTP(S) API base URL without embedded credentials")
    model_id = resolve_role_model(role, role_models=provider.config.get("role_models"), fallback_model=str(provider.config.get("model") or ""))
    if not model_id:
        raise ValueError("Research role has no actual API model ID")
    auth_required = False if runtime else provider.config.get("auth_required", protocol != "ollama") is not False
    secret_ref = None if runtime else provider.secret_ref
    if runtime: base_url = None
    fingerprint = content_hash({"provider_id": provider_id, "protocol": protocol, "base_url": base_url, "model_id": model_id,
        "auth_required": auth_required, "secret_ref": secret_ref, **({"runtime":runtime} if runtime else {})})
    return ProviderBinding(provider_id, protocol, model_id, base_url, fingerprint, secret_ref, auth_required, codex_binary, codex_home)


def validate_billing(binding: ProviderBinding, policy: ExtractionPolicy) -> None:
    expected = "codex_subscription" if binding.protocol == "codex-app-server" else "api_metered"
    if policy.billing_mode != expected:
        raise ValueError(f"Review a {expected.replace('_', ' ')} policy for the configured provider")


def pinned_binding(repo: UiRepository, model: ModelRevision) -> ProviderBinding:
    binding = resolve_provider(repo)
    if (model.provider_id, model.model_id, model.provider_config_hash) != (binding.provider_id, binding.model_id, binding.config_hash):
        raise ValueError("Research provider/model/endpoint changed or was not pinned; freeze a new revision before dispatch")
    if model.prompt_hash != prompt_hash() or model.schema_hash != schema_hash():
        raise ValueError("Model prompt/schema differs from the current extractor")
    return binding


def provider_status(repo: UiRepository) -> list[dict]:
    result = []
    for role in ("research_designer", "research_extractor"):
        try:
            binding = resolve_provider(repo, role)
            configured = not binding.auth_required or bool(binding.secret_ref)
            result.append({"role": role, "available": configured, "provider_id": binding.provider_id, "model_id": binding.model_id,
                "provider_config_hash": binding.config_hash, "billing_mode":"codex_subscription" if binding.protocol == "codex-app-server" else "api_metered",
                "message": "Codex App Server configured; ChatGPT login and model checked at dispatch. Subscription usage has no guaranteed per-call token cap." if binding.protocol == "codex-app-server" else "Configured; credential and frozen budget checked again at dispatch" if configured else "Credential reference missing"})
        except (ValueError, KeyError) as exc:
            result.append({"role": role, "available": False, "message": str(exc)})
    return result


def bounded_prompt(system: str, schema: dict) -> str:
    return system + "\nExact output JSON schema:\n" + canonical_json(schema)


def validate_input_bound(user: str, policy: ExtractionPolicy, *, system: str = SYSTEM_PROMPT, schema: dict | None = None) -> None:
    # A conservative byte bound for text tokenization plus message overhead.
    # Actual provider usage is checked as well; incompatible provider counting
    # invalidates evidence and stops subsequent calls instead of shrinking cost.
    bound = len(bounded_prompt(system, guidance_schema() if schema is None else schema).encode()) + len(user.encode()) + 4096
    if bound > policy.max_input_tokens:
        raise ValueError("Source packet exceeds the frozen conservative input-token bound")


class ProviderExtractionClient:
    def __init__(self, binding: ProviderBinding, policy: ExtractionPolicy, credential: str, *, factory=None):
        self.binding, self.policy, self.credential, self.factory = binding, policy, credential, factory

    def complete(self, *, system: str, user: str, schema: dict, images=None) -> Completion:
        validate_billing(self.binding, self.policy)
        validate_input_bound(user, self.policy, system=system, schema=schema)
        if images and self.binding.protocol != 'codex-app-server':
            raise ValueError('Image evidence requires the verified Codex adapter')
        if self.binding.protocol == "codex-app-server":
            from tradingagents.research.evidence.codex import complete
            return complete(self.binding, self.policy, system=system, user=user, schema=schema, **({'images': images} if images else {}))
        from langchain_core.messages import HumanMessage, SystemMessage
        from tradingagents.llm_clients.factory import create_llm_client
        factory = self.factory or create_llm_client
        try:
            llm = factory(self.binding.protocol, self.binding.model_id, base_url=self.binding.base_url, api_key=self.credential,
                timeout=self.policy.timeout_seconds, max_retries=0, max_tokens=self.policy.max_output_tokens).get_llm()
            response = llm.invoke([SystemMessage(content=bounded_prompt(system, schema)), HumanMessage(content=user)])
        except Exception:
            # Provider exception bodies can contain credentials or echoed headers.
            raise RuntimeError("Configured provider call failed; no retry was performed") from None
        metadata = getattr(response, "response_metadata", {}) or {}
        usage = getattr(response, "usage_metadata", {}) or metadata.get("token_usage") or metadata.get("usage") or {}
        input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
        output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
        errors = []
        valid = all(type(n) is int and n >= 0 for n in (input_tokens, output_tokens))
        cost = None
        if valid:
            cost = ((Decimal(input_tokens)*self.policy.input_usd_per_million + Decimal(output_tokens)*self.policy.output_usd_per_million)/Decimal(1000000)).quantize(Decimal(".000001"), rounding=ROUND_UP)
            if input_tokens > self.policy.max_input_tokens or output_tokens > self.policy.max_output_tokens:
                errors.append("Provider token usage exceeded a frozen bound; further dispatch must stop")
        else:
            input_tokens = output_tokens = None
            errors.append("Provider token usage was unavailable; full reservation retained")
        model_id = metadata.get("model_name") or metadata.get("model") or "unconfirmed"
        if not isinstance(model_id, str) or len(model_id) > 160:
            model_id = "unconfirmed"
        text = response.content if isinstance(response.content, str) else ""
        calls = bool(getattr(response, "tool_calls", None) or getattr(response, "invalid_tool_calls", None))
        return Completion(text=text, provider_id=self.binding.provider_id, model_id=model_id, input_tokens=input_tokens, output_tokens=output_tokens,
            cost_usd=cost, cost_basis="configured_token_rates", tool_calls=calls, validation_errors=tuple(errors))
