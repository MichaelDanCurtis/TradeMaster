"""Research-only API: no client-defined approval, broker call, or state."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException
from pydantic import Field

from tradingagents.research.contracts import (
    Contract, ExperimentInput, FreezeVersion, ResearchPlanInput, SnapshotManifest, StrategyDraft, Text,
)
from tradingagents.research.data.contracts import DatasetBundle
from tradingagents.research.data.store import ArtifactStore
from tradingagents.research.repository import ConflictError, MissingRecordError, ResearchRepository
from tradingagents.research.designer import DesignInput, StrategyDesigner, schema_info
from tradingagents.ui.room_policy import enforce_room_tool


class DraftRevision(Contract):
    draft: StrategyDraft
    expected_revision: int = Field(ge=1)


class FreezeVersionBatch(Contract):
    versions: list[FreezeVersion] = Field(min_length=1, max_length=12)


class DatasetImport(Contract):
    dataset: DatasetBundle
    provider: Text
    provenance: Text
    entitlement: Text
    calendar: Text
    evidence_kind: Literal["fixture", "historical", "prospective"]
    availability: Literal["verified_publication", "recorded_receipt", "unverified", "synthetic"]
    limitations: list[Text] = Field(default_factory=list)


def create_research_router(session_factory) -> APIRouter:
    router = APIRouter(prefix="/api/research", tags=["research"])
    repo = ResearchRepository(session_factory)
    database = session_factory.kw["bind"].url.database
    default_root = Path(database).resolve().parent / ".research-artifacts" if database and database != ":memory:" else Path.cwd() / ".research-artifacts"
    store = ArtifactStore(os.environ.get("TRADEMASTER_RESEARCH_ARTIFACTS", str(default_root)))

    def grant(permission: str):
        def dependency(x_trademaster_room: str = Header(default="research")):
            try:
                enforce_room_tool(x_trademaster_room, permission)
            except PermissionError as exc:
                raise HTTPException(status_code=403, detail=str(exc)) from exc
        return dependency

    read = [Depends(grant("strategy-read"))]
    draft = [Depends(grant("strategy-draft"))]
    run = [Depends(grant("strategy-experiment"))]

    def call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except MissingRecordError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.get("/strategies", dependencies=read)
    def strategies():
        return {"strategies": repo.list_strategies()}

    @router.post("/strategies", dependencies=draft, status_code=201)
    def create_strategy(request: StrategyDraft):
        return call(repo.create_strategy, request)

    @router.get("/strategies/{strategy_id}", dependencies=read)
    def strategy(strategy_id: str):
        return call(repo.strategy, strategy_id)

    @router.put("/strategies/{strategy_id}", dependencies=draft)
    def revise(strategy_id: str, request: DraftRevision):
        return call(repo.revise_draft, strategy_id, request.draft, request.expected_revision)

    @router.post("/strategies/{strategy_id}/versions", dependencies=draft, status_code=201)
    def freeze_version(strategy_id: str, request: FreezeVersion):
        return call(repo.freeze_version, strategy_id, request)

    @router.post("/strategies/{strategy_id}/versions/batch", dependencies=draft, status_code=201)
    def freeze_versions(strategy_id: str, request: FreezeVersionBatch):
        return {"versions": call(repo.freeze_versions, strategy_id, request.versions)}

    @router.get("/evidence/schema", dependencies=read)
    def evidence_schema():
        from tradingagents.research.evidence.extraction import prompt_hash, schema_hash
        return {"prompt_hash": prompt_hash(), "schema_hash": schema_hash(), "schema_version": "guidance_evidence_v1", "historical_latency_seconds": 60,
            "dispatch_available": True, "message": "New calls require an explicitly frozen extraction policy, current provider pin and cost reservation. Replay alone does not invoke a model."}

    @router.get("/evidence/providers", dependencies=read)
    def evidence_providers():
        from tradingagents.research.evidence.provider import provider_status
        from tradingagents.ui.repository import UiRepository
        return {"providers": provider_status(UiRepository(session_factory))}

    @router.get("/designer/schema", dependencies=read)
    def designer_schema():
        return schema_info()

    @router.get("/strategies/{strategy_id}/designs", dependencies=read)
    def designs(strategy_id: str):
        return {"designs": call(StrategyDesigner(repo).history, strategy_id)}

    @router.post("/strategies/{strategy_id}/designs", dependencies=run, status_code=202)
    def design(strategy_id: str, request: DesignInput, background: BackgroundTasks):
        designer = StrategyDesigner(repo)
        row, fresh = call(designer.reserve, strategy_id, request)
        if fresh:
            background.add_task(designer.dispatch, row.design_id)
        return row

    @router.post("/plans", dependencies=draft, status_code=201)
    def freeze_plan(request: ResearchPlanInput):
        return call(repo.freeze_plan, request)

    @router.get("/snapshots", dependencies=read)
    def snapshots():
        return {"snapshots": repo.list_snapshots()}

    @router.get("/runtime", dependencies=read)
    def runtime():
        import time
        from tradingagents.research.engines.lean import cached_availability
        result = repo.runtime()
        lean = cached_availability(int(time.monotonic() // 15))
        result["engine_capabilities"] = [{"engine": "local_replay", "available": True, "message": "Built-in deterministic research replay"}, {"engine": "lean", **lean}]
        if result["available"]:
            result["supported_engines"] = [row["engine"] for row in result["engine_capabilities"] if row["available"]]
            result["message"] = "Research worker connected"
        return result

    @router.get("/overview", dependencies=[Depends(grant("research-overview-read"))])
    def overview():
        from tradingagents.research.overview import research_overview
        from tradingagents.research.evidence.provider import provider_status
        from tradingagents.ui.repository import UiRepository
        return {**research_overview(session_factory), "runtime": runtime(),
                "providers": provider_status(UiRepository(session_factory))}

    @router.post("/datasets", dependencies=draft, status_code=201)
    def import_dataset(request: DatasetImport):
        data = request.dataset
        def save():
            artifacts = store.put_dataset(data)
            manifest = SnapshotManifest(
                **request.model_dump(exclude={"dataset"}), timezone=data.timezone,
                coverage_start=data.sessions[0].date, coverage_end=data.sessions[-1].date,
                instrument_ids=sorted({m.instrument_id for m in data.mappings}), artifacts=artifacts,
            )
            store.dataset(manifest)
            return repo.register_snapshot(manifest)
        return call(save)

    @router.post("/fixtures/trend", dependencies=draft, status_code=201)
    def trend_fixture():
        from tradingagents.research.data.fixtures import save_trend_fixture
        return call(repo.register_snapshot, save_trend_fixture(store))

    @router.post("/fixtures/guidance", dependencies=draft, status_code=201)
    def guidance_fixture():
        from tradingagents.research.data.guidance_fixture import save_guidance_fixture
        return call(repo.register_snapshot, save_guidance_fixture(store))

    @router.get("/datasets/schema", dependencies=read)
    def dataset_schema():
        return DatasetImport.model_json_schema()

    @router.get("/fixtures/trend/dataset", dependencies=read)
    def trend_import_example():
        from tradingagents.research.data.fixtures import trend_fixture
        return DatasetImport(dataset=trend_fixture(), provider="synthetic_trend_fixture",
            provenance="Deterministic synthetic prices for software testing only", entitlement="Repository-generated test data",
            calendar="synthetic_weekdays", evidence_kind="fixture", availability="synthetic",
            limitations=["Synthetic weekdays include exchange holidays; no investment-performance inference"])

    @router.post("/snapshots", dependencies=draft, status_code=201)
    def snapshot(request: SnapshotManifest):
        return call(repo.register_snapshot, request)

    @router.post("/experiments", dependencies=run, status_code=202)
    def queue(request: ExperimentInput):
        return call(repo.queue_experiment, request)

    @router.get("/experiments/{experiment_id}", dependencies=read)
    def experiment(experiment_id: str):
        return call(repo.experiment, experiment_id)

    @router.get("/experiments/{experiment_id}/events", dependencies=read)
    def events(experiment_id: str):
        return {"events": call(repo.events, experiment_id)}

    @router.get("/experiments/{experiment_id}/model-calls", dependencies=read)
    def model_calls(experiment_id: str):
        return {"calls": call(repo.model_calls, experiment_id)}

    @router.get("/experiments/{experiment_id}/model-calls/{call_id}/evidence", dependencies=read)
    def model_evidence(experiment_id: str, call_id: str):
        rows = call(repo.model_calls, experiment_id)
        row = next((r for r in rows if r.call_id == call_id), None)
        if row is None or row.output_artifact is None:
            raise HTTPException(status_code=404, detail="No preserved model receipt for this attempt")
        try:
            return store.json(row.output_artifact)
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=409, detail="Model receipt is missing or failed integrity verification") from exc

    @router.get("/experiments/{experiment_id}/artifacts/{digest}", dependencies=read)
    def artifact(experiment_id: str, digest: str):
        record = call(repo.experiment, experiment_id)
        if record.result is None or digest not in record.result.get("artifacts", {}).values():
            raise HTTPException(status_code=404, detail="Artifact is not part of this experiment")
        try:
            return store.json(digest)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=409, detail="Experiment artifact is missing") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail="Experiment artifact failed verification") from exc

    @router.post("/experiments/{experiment_id}/cancel", dependencies=run)
    def cancel(experiment_id: str):
        return call(repo.cancel, experiment_id)

    @router.get("/strategies/{strategy_id}/experiments", dependencies=read)
    def experiments(strategy_id: str):
        return {"experiments": call(repo.experiments, strategy_id)}

    return router
