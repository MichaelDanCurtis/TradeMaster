from datetime import timedelta
from decimal import Decimal as D
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from sqlalchemy import text

from tradingagents.research.contracts import ExtractionPolicy, ExperimentInput, FreezeVersion, ResearchPlanInput, SnapshotManifest, StrategyDraft, content_hash
from tradingagents.research.data.guidance_fixture import guidance_fixture, fixture_guidance_spec
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.evidence.extraction import extraction_input, input_hash
from tradingagents.research.evidence.provider import ProviderBinding, ProviderExtractionClient, pinned_binding, provider_status, resolve_provider, validate_input_bound
from tradingagents.research.repository import ConflictError
from tradingagents.research.worker import ResearchWorker
from tradingagents.ui.repository import UiRepository
from tests.research.conftest import plan_payload


def policy(**changes):
    return ExtractionPolicy(max_calls=1, input_usd_per_million=1, output_usd_per_million=2,
        pricing_reference="Local test rates; no paid provider", **changes)


@pytest.fixture
def endpoint():
    state = SimpleNamespace(requests=[], raw=next(e.raw_output for e in guidance_fixture().evidence if e.notice_id == "clean-raise"), status=200, before=None, output_tokens=100, release=None, received=Event())
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state.requests.append((self.path, body, self.headers.get("Authorization")))
            if state.before:
                state.before()
            state.received.set()
            if state.release:
                state.release.wait(timeout=5)
            response = {"id": "local-test", "object": "chat.completion", "created": 1, "model": "provider-test-v1",
                "choices": [{"index": 0, "message": {"role": "assistant", "content": state.raw}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": state.output_tokens, "total_tokens": 100 + state.output_tokens}}
            if self.path == "/v1/responses":
                response = {"id": "resp_local", "object": "response", "created_at": 1, "model": "provider-test-v1", "status": "completed", "error": None,
                    "output": [{"type": "message", "id": "msg_local", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": state.raw, "annotations": []}]}],
                    "usage": {"input_tokens": 100, "output_tokens": state.output_tokens, "total_tokens": 100 + state.output_tokens,
                        "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}, "service_tier": "default"}
            elif self.path == "/v1/messages":
                response = {"id": "msg_local", "type": "message", "role": "assistant", "model": "provider-test-v1",
                    "content": [{"type": "text", "text": state.raw}], "stop_reason": "end_turn", "stop_sequence": None,
                    "usage": {"input_tokens": 100, "output_tokens": state.output_tokens}}
            data = json.dumps(response if state.status == 200 else {"error": {"message": "provider unavailable", "type": "server_error"}}).encode()
            self.send_response(state.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    state.url = f"http://127.0.0.1:{server.server_port}/v1"
    thread = Thread(target=server.serve_forever, kwargs={"poll_interval": .02}, daemon=True)
    thread.start()
    yield state
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def setup_dispatch(repository, tmp_path, endpoint, monkeypatch, *, extraction_policy=None, include_repeat=False, family_budget="10", protocol="openai-compatible"):
    monkeypatch.setenv("TRADEMASTER_TEST_EXTRACT_KEY", "selected-test-credential")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "never-pass-this-broker-key")
    registry = UiRepository(repository.sessions)
    base_url = endpoint.url.removesuffix("/v1") if protocol == "anthropic" else endpoint.url
    provider = registry.create_user_provider(name="Bounded test provider", kind="openai-compatible", base_url=base_url,
        model="provider-test-v1", api_key_env="env:TRADEMASTER_TEST_EXTRACT_KEY")
    registry.upsert_provider_config(provider.provider_id, enabled=True, config={**provider.config, "provider": protocol})
    registry.upsert_provider_role_assignment("research_extractor", provider_id=provider.provider_id)
    binding = resolve_provider(registry)
    dataset = guidance_fixture()
    dataset.evidence = []
    notice_ids = {"clean-prior", "clean-raise", "clean-repeat"} if include_repeat else {"clean-prior", "clean-raise"}
    dataset.guidance_notices = [n for n in dataset.guidance_notices if n.notice_id in notice_ids]
    dataset.human_labels = [label for label in dataset.human_labels if label.notice_id == "clean-raise"]
    for row in [*dataset.documents, *dataset.financials, *dataset.guidance_notices]:
        row.availability.mode = "historical"
        row.availability.latency_assumption = "Test-only history for the local fake-provider boundary"
    store = ArtifactStore(tmp_path/"dispatch-artifacts")
    manifest = SnapshotManifest(provider="test-source", evidence_kind="historical", provenance="Local integration test, not genuine market evidence",
        entitlement="Synthetic test source", calendar="test-weekdays", timezone=dataset.timezone, coverage_start=dataset.sessions[0].date,
        coverage_end=dataset.sessions[-1].date, instrument_ids=sorted(m.instrument_id for m in dataset.mappings),
        artifacts=store.put_dataset(dataset), availability="verified_publication")
    snapshot = repository.register_snapshot(manifest)
    strategy = repository.create_strategy(StrategyDraft(name="Provider boundary", hypothesis="One exact extraction", rationale="Local HTTP server verification"))
    specs = [fixture_guidance_spec(arm) for arm in ("guidance_control", "numeric_quality", "astra_challenger")]
    for spec in specs:
        spec.universe = [i for i in spec.universe if i.instrument_id == "sim-clean"]
        if spec.model:
            spec.model.provider_id = binding.provider_id
            spec.model.model_id = binding.model_id
            spec.model.provider_config_hash = binding.config_hash
    versions = repository.freeze_versions(strategy.strategy_id, [FreezeVersion(spec=s) for s in specs])
    payload = plan_payload(strategy.strategy_id, versions[0].version_id)
    payload["version_ids"] = [v.version_id for v in versions]
    payload["extraction"] = (extraction_policy or policy()).model_dump(mode="json")
    payload["compute_budget_usd"] = family_budget
    plan = repository.freeze_plan(ResearchPlanInput.model_validate(payload))
    job = repository.queue_experiment(ExperimentInput(plan_id=plan.plan_id, snapshot_id=snapshot.snapshot_id, idempotency_key="dispatch-test"))
    return store, job, registry, specs[-1], binding


def test_real_sdk_child_precharges_once_and_offline_report_preserves_receipt(repository, tmp_path, endpoint, monkeypatch):
    store, job, registry, spec, binding = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    seen = []
    def before():
        calls = repository.model_calls(job.experiment_id)
        seen.append((len(calls), calls[0].state, calls[0].charged_cost_usd, repository.experiment(job.experiment_id).cost_usd))
    endpoint.before = before
    ResearchWorker(repository, store).run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "completed", final.failure_reason
    assert seen == [(1, "dispatched", "0.036864", "0.036864")]
    assert len(endpoint.requests) == 1
    path, body, auth = endpoint.requests[0]
    assert path == "/v1/chat/completions" and auth == "Bearer selected-test-credential"
    assert body["model"] == "provider-test-v1" and body["max_completion_tokens"] == 2048
    assert "tools" not in body and body["messages"][0]["role"] == "system"
    assert "expected_verdict" not in body["messages"][1]["content"]
    assert D(final.cost_usd) == D(".0003")
    calls = repository.model_calls(job.experiment_id)
    assert calls[0].state == "completed" and calls[0].failure_reason is None
    evidence = store.json(calls[0].output_artifact)
    assert evidence["actual_model_id"] == "provider-test-v1" and evidence["cost_basis"] == "configured_token_rates"
    assert evidence["classification"]["one_time_dependency"] == "no"
    report = final.result["report"]
    assert report["model_call_ids"] == [calls[0].call_id]
    assert report["model_call_costs"] == {content_hash(spec.model): "0.000300"}
    assert report["evaluated_dataset_hash"] != repository.inputs(job.experiment_id)[2].artifacts["dataset"]
    for artifact in final.result["artifacts"].values():
        data = store.get(artifact)
        assert b"selected-test-credential" not in data and b"never-pass-this-broker-key" not in data
    assert ResearchWorker(repository, store).run_once() is None and len(endpoint.requests) == 1
    with repository.sessions() as session, pytest.raises(Exception, match="immutable"):
        session.execute(text("UPDATE research_model_calls SET charged_cost_usd='0' WHERE call_id=:id"), {"id": calls[0].call_id})


def test_provider_error_has_no_sdk_retry_and_retains_unknown_charge(repository, tmp_path, endpoint, monkeypatch):
    endpoint.status = 503
    store, job, _, _, _ = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    ResearchWorker(repository, store).run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "completed", final.failure_reason
    assert len(endpoint.requests) == 1
    call = repository.model_calls(job.experiment_id)[0]
    assert call.state == "unknown" and D(call.charged_cost_usd) == policy().maximum_call_cost_usd
    assert store.json(call.output_artifact)["classification"] is None
    assert all(a["evidence_status"] != "eligible_for_paper_review" for a in final.result["report"]["assessments"])


def test_restart_after_dispatch_does_not_repeat_an_ambiguous_economic_call(repository, tmp_path, endpoint, monkeypatch):
    store, job, _, spec, binding = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    repository.claim("old")
    dataset = store.dataset(repository.inputs(job.experiment_id)[2])
    notice = next(n for n in dataset.guidance_notices if n.notice_id == "clean-raise")
    version_id = repository.inputs(job.experiment_id)[1].version_ids[-1]
    row, fresh = repository.reserve_model_call(job.experiment_id, "old", version_id=version_id, notice_id=notice.notice_id,
        input_hash=input_hash(extraction_input(dataset, notice, notice.availability.available_at)), input_as_of=notice.availability.available_at, provider_fingerprint=binding.config_hash)
    repository.dispatch_model_call(row.call_id, "old")
    with repository.sessions() as session:
        current = session.get(type(job), job.experiment_id)
        current.lease_until -= timedelta(hours=1)
        session.add(current)
        session.commit()
    ResearchWorker(repository, store, worker_id="new").run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "completed", final.failure_reason
    assert endpoint.requests == []
    assert repository.model_calls(job.experiment_id)[0].state == "unknown"
    assert D(final.cost_usd) == policy().maximum_call_cost_usd
    assert final.result["report"]["model_call_costs"][content_hash(spec.model)] == "0.036864"


def test_changed_provider_pin_stops_before_network(repository, tmp_path, endpoint, monkeypatch):
    store, job, registry, spec, binding = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    provider = registry.get_provider_config(binding.provider_id)
    registry.upsert_provider_config(binding.provider_id, config={**provider.config, "model": "changed-model"})
    with pytest.raises(ValueError, match="changed or was not pinned"):
        pinned_binding(registry, spec.model)
    ResearchWorker(repository, store).run_once()
    assert repository.experiment(job.experiment_id).state == "failed"
    assert endpoint.requests == [] and repository.model_calls(job.experiment_id) == []


def test_concurrent_reservation_is_idempotent_and_never_refills_call_limit(repository, tmp_path, endpoint, monkeypatch):
    store, job, _, spec, binding = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    repository.claim("owner")
    dataset = store.dataset(repository.inputs(job.experiment_id)[2])
    notice = next(n for n in dataset.guidance_notices if n.notice_id == "clean-raise")
    kwargs = dict(version_id=repository.inputs(job.experiment_id)[1].version_ids[-1], notice_id=notice.notice_id,
        input_hash=input_hash(extraction_input(dataset, notice, notice.availability.available_at)), input_as_of=notice.availability.available_at, provider_fingerprint=binding.config_hash)
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: repository.reserve_model_call(job.experiment_id, "owner", **kwargs), range(2)))
    assert sum(fresh for _, fresh in results) == 1
    assert len({r.call_id for r, _ in results}) == 1
    assert D(repository.experiment(job.experiment_id).cost_usd) == policy().maximum_call_cost_usd
    with pytest.raises(ConflictError, match="call limit"):
        repository.reserve_model_call(job.experiment_id, "owner", **{**kwargs, "input_hash": "a"*64})


def test_codex_research_reports_subscription_contract_instead_of_api_caps(repository, monkeypatch):
    monkeypatch.setattr("tradingagents.research.evidence.codex.runtime_paths", lambda config: ("/test/codex", "/test/home", {"adapter":"test"}))
    registry = UiRepository(repository.sessions)
    registry.set_developer_mode_enabled(True)
    registry.upsert_provider_role_assignment("research_extractor", provider_id="openai-codex-oauth-llm")
    status = next(r for r in provider_status(registry) if r["role"] == "research_extractor")
    assert status["available"] and status["billing_mode"] == "codex_subscription"
    assert "no guaranteed per-call token cap" in status["message"]


def test_input_bound_and_unconfirmed_response_metadata_abstain():
    with pytest.raises(ValueError, match="input-token bound"):
        validate_input_bound("x"*40000, policy())
    binding = ProviderBinding("test", "openai-compatible", "pinned", None, "a"*64, None, False)
    seen = {}
    class Llm:
        def invoke(self, messages):
            return SimpleNamespace(content="{}", response_metadata={}, usage_metadata={}, tool_calls=[])
    def factory(*args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(get_llm=lambda: Llm())
    result = ProviderExtractionClient(binding, policy(), "dummy", factory=factory).complete(system="system", user="{}", schema={})
    assert seen["max_retries"] == 0 and seen["max_tokens"] == 2048
    assert result.model_id == "unconfirmed" and result.cost_usd is None and result.validation_errors


def test_provider_overrun_preserves_receipt_and_stops_dispatch(repository, tmp_path, endpoint, monkeypatch):
    endpoint.output_tokens = 99999
    store, job, _, _, _ = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    ResearchWorker(repository, store).run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "failed" and "exceeded" in final.failure_reason
    call = repository.model_calls(job.experiment_id)[0]
    assert D(call.charged_cost_usd) == D(".200098") > D(call.reserved_cost_usd)
    assert D(final.cost_usd) == D(call.charged_cost_usd)
    assert "bound" in call.failure_reason and store.json(call.output_artifact)["validation_errors"]
    assert len(endpoint.requests) == 1
    # The receipt is inspectable even when the experiment has no result, but
    # unrelated call IDs and modified artifact content cannot be retrieved.
    from fastapi.testclient import TestClient
    from tradingagents.ui.api import create_app
    monkeypatch.setenv("TRADEMASTER_RESEARCH_ARTIFACTS", str(store.root))
    client = TestClient(create_app(str(repository.sessions.kw["bind"].url)))
    path = f"/api/research/experiments/{job.experiment_id}/model-calls"
    assert client.get(path).json()["calls"][0]["call_id"] == call.call_id
    assert client.get(f"{path}/{call.call_id}/evidence").json()["output_tokens"] == 99999
    assert client.get(f"{path}/unrelated/evidence").status_code == 404
    store.path(call.output_artifact).write_text("{}")
    assert client.get(f"{path}/{call.call_id}/evidence").status_code == 409


def test_cancellation_terminates_model_process_without_releasing_unknown_charge(repository, tmp_path, endpoint, monkeypatch):
    endpoint.release = Event()
    store, job, _, _, _ = setup_dispatch(repository, tmp_path, endpoint, monkeypatch)
    thread = Thread(target=ResearchWorker(repository, store).run_once)
    thread.start()
    try:
        assert endpoint.received.wait(timeout=5)
        repository.cancel(job.experiment_id)
        thread.join(timeout=4)
        assert not thread.is_alive()
        assert repository.experiment(job.experiment_id).state == "cancelled"
        call = repository.model_calls(job.experiment_id)[0]
        assert call.state == "unknown" and call.output_artifact is None
        assert D(call.charged_cost_usd) == policy().maximum_call_cost_usd
        assert ResearchWorker(repository, store).run_once() is None and len(endpoint.requests) == 1
    finally:
        endpoint.release.set()
        thread.join(timeout=5)


def test_too_many_candidates_fails_before_any_model_selection_or_charge(repository, tmp_path, endpoint, monkeypatch):
    store, job, _, _, _ = setup_dispatch(repository, tmp_path, endpoint, monkeypatch, include_repeat=True)
    ResearchWorker(repository, store).run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "failed" and "no partial selection" in final.failure_reason
    assert endpoint.requests == [] and repository.model_calls(job.experiment_id) == [] and D(final.cost_usd) == 0


def test_family_reservations_prevent_two_experiments_spending_the_same_budget(repository, tmp_path, endpoint, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    store, job, _, _, binding = setup_dispatch(repository, tmp_path, endpoint, monkeypatch, family_budget=".04")
    other = repository.queue_experiment(ExperimentInput(plan_id=job.plan_id, snapshot_id=job.snapshot_id, idempotency_key="other-attempt"))
    repository.claim("first")
    repository.claim("second")
    dataset = store.dataset(repository.inputs(job.experiment_id)[2])
    notice = next(n for n in dataset.guidance_notices if n.notice_id == "clean-raise")
    kwargs = dict(version_id=repository.inputs(job.experiment_id)[1].version_ids[-1], notice_id=notice.notice_id,
        input_hash=input_hash(extraction_input(dataset, notice, notice.availability.available_at)), input_as_of=notice.availability.available_at, provider_fingerprint=binding.config_hash)
    def reserve(pair):
        try:
            return repository.reserve_model_call(pair[0], pair[1], **kwargs)
        except ConflictError as exc:
            return exc
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(reserve, [(job.experiment_id, "first"), (other.experiment_id, "second")]))
    assert sum(isinstance(result, ConflictError) for result in results) == 1
    assert sum(D(repository.experiment(j.experiment_id).cost_usd) for j in (job, other)) == policy().maximum_call_cost_usd
    assert endpoint.requests == []


def test_native_openai_responses_request_keeps_the_output_cap():
    from langchain_core.messages import HumanMessage
    from tradingagents.llm_clients.factory import create_llm_client
    llm = create_llm_client("openai", "pinned-test-model", api_key="test-only", max_tokens=128, max_retries=0).get_llm()
    payload = llm._get_request_payload([HumanMessage(content="Local serialization test; no HTTP request")])
    assert payload["max_output_tokens"] == 128 and payload["model"] == "pinned-test-model"


@pytest.mark.parametrize("protocol,route,cap", [("openai", "/v1/responses", "max_output_tokens"), ("anthropic", "/v1/messages", "max_tokens")])
def test_native_provider_sdk_roundtrip_preserves_output_identity_and_metering(repository, tmp_path, endpoint, monkeypatch, protocol, route, cap):
    endpoint.raw = " \n" + endpoint.raw + "\n "
    store, job, _, _, _ = setup_dispatch(repository, tmp_path, endpoint, monkeypatch, protocol=protocol)
    ResearchWorker(repository, store).run_once()
    final = repository.experiment(job.experiment_id)
    assert final.state == "completed", final.failure_reason
    assert len(endpoint.requests) == 1
    path, body, _ = endpoint.requests[0]
    assert path == route and body[cap] == 2048 and "tools" not in body
    call = repository.model_calls(job.experiment_id)[0]
    receipt = store.json(call.output_artifact)
    assert call.state == "completed" and receipt["validation_errors"] == []
    assert receipt["raw_output"] == endpoint.raw and receipt["actual_model_id"] == "provider-test-v1"
    assert D(final.cost_usd) == D(".000300")
