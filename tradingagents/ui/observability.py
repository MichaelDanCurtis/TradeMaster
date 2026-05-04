from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Protocol

from tradingagents.ui.models import ObservabilityTraceRecord
from tradingagents.ui.repository import UiRepository
from tradingagents.ui.secrets import SecretStore


LANGFUSE_PROVIDER_ID = "langfuse-observability"
_ROOT_PARENT_SPAN_ID = "0123456789abcdef"


class LangfuseObservation(Protocol):
    trace_id: str

    def __enter__(self) -> "LangfuseObservation":
        ...

    def __exit__(self, exc_type, exc, traceback) -> None:
        ...

    def update(self, **kwargs: Any) -> None:
        ...


class LangfuseClient(Protocol):
    def create_trace_id(self, seed: str) -> str:
        ...

    def start_as_current_observation(self, **kwargs: Any) -> LangfuseObservation:
        ...

    def get_trace_url(self, *, trace_id: str) -> str:
        ...

    def flush(self) -> None:
        ...


@dataclass(frozen=True)
class LangfuseCredentials:
    public_key: str
    secret_key: str
    base_url: str = "https://cloud.langfuse.com"


SecretStoreFactory = Callable[[str], SecretStore]
LangfuseClientFactory = Callable[[LangfuseCredentials], LangfuseClient]


class ObservabilityService:
    def __init__(
        self,
        repository: UiRepository,
        *,
        secret_store_factory: SecretStoreFactory | None = None,
        langfuse_client_factory: LangfuseClientFactory | None = None,
    ) -> None:
        self._repository = repository
        self._secret_store_factory = secret_store_factory or _default_secret_store_factory
        self._langfuse_client_factory = langfuse_client_factory or _default_langfuse_client_factory

    def export_run_trace(self, run_id: str) -> ObservabilityTraceRecord:
        trace = self._repository.get_observability_trace(run_id)
        run = self._repository.get_run(run_id)
        provider = self._repository.get_provider_config(LANGFUSE_PROVIDER_ID)
        if not provider.enabled or provider.secret_ref is None:
            raise PermissionError("LangFuse observability is disabled or missing a secret_ref")

        secret_store = self._secret_store_factory(provider.secret_ref)
        credentials = _parse_langfuse_credentials(
            secret_store.get_secret(provider.secret_ref)
        )
        client = self._langfuse_client_factory(credentials)
        external_trace_id = client.create_trace_id(seed=run_id)
        metadata = _langfuse_metadata(trace)

        with client.start_as_current_observation(
            as_type="span",
            name="tradingagents.run",
            input={
                "run_id": run_id,
                "ticker": run.ticker,
                "trade_date": run.trade_date,
            },
            metadata=metadata,
            trace_context={
                "trace_id": external_trace_id,
                "parent_span_id": _ROOT_PARENT_SPAN_ID,
            },
        ) as span:
            span.update(
                output={
                    "status": run.status,
                    "final_action": run.final_action,
                    "final_rating": run.final_rating,
                },
                level="ERROR" if run.status == "failed" else "DEFAULT",
                status_message=f"TradingAgents run {run.status}",
            )
        trace_url = client.get_trace_url(trace_id=external_trace_id)
        client.flush()

        exported = self._repository.update_observability_trace(
            run_id,
            status="exported",
            provider=LANGFUSE_PROVIDER_ID,
            external_trace_id=external_trace_id,
            metadata={
                "export_status": "exported",
                "exported_to": "langfuse",
                "external_trace_url": trace_url,
            },
        )
        self._repository.append_private_office_event(
            event_type="observability.trace_exported",
            summary=f"Exported LangFuse trace for {run.ticker} run.",
            actor="Observability",
            entity_id=run_id,
            payload={
                "run_id": run_id,
                "provider_id": LANGFUSE_PROVIDER_ID,
                "external_trace_id": external_trace_id,
                "external_trace_url": trace_url,
            },
        )
        return exported


def _parse_langfuse_credentials(raw_secret: str) -> LangfuseCredentials:
    try:
        payload = json.loads(raw_secret)
    except json.JSONDecodeError as exc:
        raise ValueError("LangFuse secret must be JSON") from exc
    public_key = str(payload.get("public_key") or "").strip()
    secret_key = str(payload.get("secret_key") or "").strip()
    base_url = str(
        payload.get("base_url") or payload.get("host") or "https://cloud.langfuse.com"
    ).strip()
    if not public_key or not secret_key:
        raise ValueError("LangFuse secret must include public_key and secret_key")
    return LangfuseCredentials(
        public_key=public_key,
        secret_key=secret_key,
        base_url=base_url.rstrip("/"),
    )


def _langfuse_metadata(trace: ObservabilityTraceRecord) -> dict[str, object]:
    return {
        "trace_id": trace.trace_id,
        "run_id": trace.run_id,
        **dict(trace.metadata_payload),
        "local_status": trace.status,
    }


def _default_secret_store_factory(secret_ref: str) -> SecretStore:
    from tradingagents.ui.api import _secret_store_for_ref

    return _secret_store_for_ref(secret_ref)


def _default_langfuse_client_factory(credentials: LangfuseCredentials) -> LangfuseClient:
    try:
        from langfuse import Langfuse
    except ImportError as exc:
        raise RuntimeError(
            "LangFuse export requires the langfuse Python package to be installed"
        ) from exc
    return Langfuse(
        public_key=credentials.public_key,
        secret_key=credentials.secret_key,
        base_url=credentials.base_url,
    )
