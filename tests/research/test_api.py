import sqlite3

from fastapi.testclient import TestClient

from tradingagents.ui.api import create_app
from tests.research.conftest import plan_payload, snapshot_payload, spec_payload


def test_full_research_api_persists_and_rejects_authority(tmp_path):
    url = f"sqlite:///{tmp_path / 'ui.db'}"
    client = TestClient(create_app(url))
    assert client.get("/api/research/strategies").json() == {"strategies": []}
    draft = {"name": "Trend", "hypothesis": "Persistence", "rationale": "A control"}
    assert client.post("/api/research/strategies", json={**draft, "state": "paper_active"}).status_code == 422
    assert client.post("/api/research/strategies", json=draft, headers={"X-Trademaster-Room": "market"}).status_code == 403
    strategy = client.post("/api/research/strategies", json=draft).json()
    sid = strategy["strategy_id"]
    version_response = client.post(f"/api/research/strategies/{sid}/versions", json={"spec": spec_payload()})
    assert version_response.status_code == 201, version_response.text
    version = version_response.json()
    plan_response = client.post("/api/research/plans", json=plan_payload(sid, version["version_id"]))
    assert plan_response.status_code == 201, plan_response.text
    snap = client.post("/api/research/snapshots", json=snapshot_payload()).json()
    request = {"plan_id": plan_response.json()["plan_id"], "snapshot_id": snap["snapshot_id"], "idempotency_key": "api_run"}
    run = client.post("/api/research/experiments", json=request)
    assert run.status_code == 202, run.text
    assert run.json()["result"] is None
    assert client.post("/api/research/experiments", json={**request, "engine": "live"}).status_code == 422
    assert client.post("/api/research/experiments", json={**request, "evaluation": "validation"}).status_code == 409
    reloaded = TestClient(create_app(url))
    history = reloaded.get(f"/api/research/strategies/{sid}/experiments").json()["experiments"]
    assert len(history) == 1 and history[0]["state"] == "queued"
    assert reloaded.get("/api/research/experiments/missing").status_code == 404


def test_additive_initialization_preserves_legacy_records(tmp_path):
    path = tmp_path / "old.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE user_legacy_notes (id INTEGER PRIMARY KEY, note TEXT)")
        connection.execute("INSERT INTO user_legacy_notes VALUES (1, 'preserve existing data')")
    create_app(f"sqlite:///{path}")
    create_app(f"sqlite:///{path}")
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT note FROM user_legacy_notes").fetchone()[0] == "preserve existing data"
        assert connection.execute("SELECT COUNT(*) FROM research_strategies").fetchone()[0] == 0


def test_initialization_preserves_actual_existing_ui_run(tmp_path):
    from sqlmodel import Session
    from tradingagents.ui.db import create_session_factory
    from tradingagents.ui.models import RunRecord
    path = tmp_path / "legacy-ui.db"
    engine, _ = create_session_factory(f"sqlite:///{path}")
    RunRecord.__table__.create(engine)
    with Session(engine) as session:
        session.add(RunRecord(run_id="old_run", ticker="SPY", trade_date="2020-01-02", status="completed", config={"preserve": "yes"}))
        session.commit()
    create_app(f"sqlite:///{path}")
    with Session(engine) as session:
        record = session.get(RunRecord, "old_run")
        assert record.config == {"preserve": "yes"} and record.status == "completed"


def test_import_verifies_dataset_and_persists_snapshot(tmp_path):
    from tests.research.test_data import dataset_payload
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'data.db'}"))
    payload = {
        "dataset": dataset_payload(), "provider": "test", "provenance": "Hand-labelled source timing sample",
        "entitlement": "Fixture", "calendar": "test", "evidence_kind": "historical", "availability": "verified_publication",
    }
    imported = client.post("/api/research/datasets", json=payload)
    assert imported.status_code == 201, imported.text
    manifest = imported.json()["payload"]
    assert set(manifest["artifacts"]) == {"dataset", "bars_parquet"}
    assert manifest["instrument_ids"] == ["company"]
    assert client.post("/api/research/datasets", json=payload).json()["snapshot_id"] == imported.json()["snapshot_id"]
    payload["dataset"]["bars"][0]["available_at"] = "2020-05-01T12:00:00Z"
    assert client.post("/api/research/datasets", json=payload).status_code == 422


def test_downloadable_fixture_roundtrips_through_import_and_runtime_is_honest(tmp_path):
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'example.db'}"))
    runtime = client.get("/api/research/runtime").json()
    assert runtime["available"] is False and runtime["supported_engines"] == []
    example = client.get("/api/research/fixtures/trend/dataset")
    assert example.status_code == 200
    assert client.get("/api/research/datasets/schema").json()["additionalProperties"] is False
    imported = client.post("/api/research/datasets", json=example.json())
    assert imported.status_code == 201 and imported.json()["evidence_kind"] == "fixture"


def test_guidance_batch_is_atomic_matched_and_pins_the_actual_schema(tmp_path):
    from tradingagents.research.data.guidance_fixture import fixture_guidance_spec
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'guidance.db'}"))
    strategy = client.post("/api/research/strategies", json={"name": "Guidance", "hypothesis": "Compare filters", "rationale": "Engineering check"}).json()
    sid = strategy["strategy_id"]
    schema = client.get("/api/research/evidence/schema").json()
    specs = [fixture_guidance_spec(arm).model_dump(mode="json") for arm in ("guidance_control", "numeric_quality", "astra_challenger")]
    assert specs[2]["model"]["schema_hash"] == schema["schema_hash"]
    assert schema["dispatch_available"] is True
    path = f"/api/research/strategies/{sid}/versions/batch"
    broken = [{"spec": spec} for spec in specs]
    broken[2]["parent_version_id"] = "missing-parent"
    assert client.post(path, json={"versions": broken}).status_code == 404
    assert client.get(f"/api/research/strategies/{sid}").json()["versions"] == []
    payload = {"versions": [{"spec": spec} for spec in specs]}
    saved = client.post(path, json=payload)
    assert saved.status_code == 201, saved.text
    assert client.post(path, json=payload).json() == saved.json()
    assert client.post(path, json=payload, headers={"X-Trademaster-Room": "quant"}).status_code == 403
    versions = saved.json()["versions"]
    unmatched = plan_payload(sid, versions[0]["version_id"])
    assert client.post("/api/research/plans", json=unmatched).status_code == 422
    unmatched["version_ids"] = [v["version_id"] for v in versions]
    assert client.post("/api/research/plans", json=unmatched).status_code == 201
    snapshot = client.post("/api/research/fixtures/guidance", json={})
    assert snapshot.status_code == 201 and snapshot.json()["evidence_kind"] == "fixture"


def test_artifact_endpoint_checks_experiment_membership_and_content_integrity(repository, tmp_path, monkeypatch):
    from tests.research.test_worker import queue_fixture
    from tradingagents.research.worker import ResearchWorker
    store, job, _ = queue_fixture(repository, tmp_path)
    ResearchWorker(repository, store).run_once()
    record = repository.experiment(job.experiment_id)
    assert record.state == "completed", record.failure_reason
    monkeypatch.setenv("TRADEMASTER_RESEARCH_ARTIFACTS", str(store.root))
    client = TestClient(create_app(str(repository.sessions.kw["bind"].url)))
    digest = record.result["artifacts"]["report"]
    endpoint = f"/api/research/experiments/{job.experiment_id}/artifacts"
    assert client.get(f"{endpoint}/{digest}").json()["snapshot_kind"] == "fixture"
    unrelated = store.put_json({"unrelated": "artifact"})
    assert client.get(f"{endpoint}/{unrelated}").status_code == 404
    store.path(digest).write_text("{}")
    assert client.get(f"{endpoint}/{digest}").status_code == 409
