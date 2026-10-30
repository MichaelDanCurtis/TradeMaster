from __future__ import annotations

from typing import Any

from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, select

from tradingagents.ui.events import RunConfig, RunEvent, RunStatus, RunSummary
from tradingagents.ui.models import (
    AgentOperationRecord,
    AgentPackRecord,
    AgentTriggerRecord,
    AgentWorkflowRecord,
    AppSettingRecord,
    ApprovalLedgerRecord,
    ApprovalRecord,
    BrokerOrderRecord,
    DecisionRecord,
    ExecutionProgramEventRecord,
    ExecutionProgramRecord,
    FundingAllocationReviewRecord,
    ImportedAgentRecord,
    ImportedSkillRecord,
    MarketDataSnapshotRecord,
    McpConnectorRecord,
    ObservabilityTraceRecord,
    PrivateOfficeEdgeRecord,
    PrivateOfficeEntityRecord,
    PrivateOfficeEventRecord,
    PortfolioMandateRecord,
    PortfolioReviewRecord,
    ProviderConfigRecord,
    ProviderRoleAssignmentRecord,
    QuickScanRecord,
    ReportScheduleRecord,
    RunEventRecord,
    RunRecord,
    SnapshotManifestRecord,
    TradeThesisRecord,
    TradeIntentRecord,
    WatcherFireRecord,
    WatcherRecord,
    now_utc,
)
from tradingagents.ui.providers import (
    DEFAULT_PROVIDER_ROLE_ASSIGNMENTS,
    PROVIDERS,
    default_provider_config,
    provider_descriptor_by_id,
)


class UiRepository:
    _AGENT_OPERATION_TYPES = {
        "research_report",
        "portfolio_review",
        "execution_preview",
        "trigger_evaluation",
        "builder_workflow",
    }
    _AGENT_OPERATION_STATUSES = {"queued", "running", "completed", "failed"}
    _AGENT_OPERATION_AUTHORITIES = {
        "research_only",
        "paper_only",
        "approval_required",
    }
    _EXECUTION_OPERATION_TYPES = {"execution_preview"}

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def get_research_runner_mode(self) -> str:
        with self._session_factory() as session:
            record = session.get(AppSettingRecord, "research_runner")
            if record is None:
                return "llm-ui-runner"
            mode = record.value.get("mode")
            if mode in {"llm-ui-runner", "tradingagents-graph-runner"}:
                return str(mode)
            return "llm-ui-runner"

    def set_research_runner_mode(self, mode: str) -> AppSettingRecord:
        if mode not in {"llm-ui-runner", "tradingagents-graph-runner"}:
            raise ValueError("research runner mode must be llm-ui-runner or tradingagents-graph-runner")
        with self._session_factory() as session:
            record = session.get(AppSettingRecord, "research_runner")
            if record is None:
                record = AppSettingRecord(setting_key="research_runner")
            record.value = {"mode": mode}
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_developer_mode_enabled(self) -> bool:
        with self._session_factory() as session:
            record = session.get(AppSettingRecord, "developer_mode")
            if record is None:
                return False
            return bool(record.value.get("enabled", False))

    def set_developer_mode_enabled(self, enabled: bool) -> AppSettingRecord:
        with self._session_factory() as session:
            record = session.get(AppSettingRecord, "developer_mode")
            if record is None:
                record = AppSettingRecord(setting_key="developer_mode")
            record.value = {"enabled": bool(enabled)}
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def create_run(self, config: RunConfig) -> RunSummary:
        now = now_utc()
        record = RunRecord(
            ticker=config.ticker,
            trade_date=config.trade_date,
            status=RunStatus.QUEUED.value,
            config=config.model_dump(mode="json"),
            created_at=now,
            updated_at=now,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._run_summary(record)

    def get_run(self, run_id: str) -> RunSummary:
        with self._session_factory() as session:
            record = session.get(RunRecord, run_id)
            if record is None:
                raise KeyError(run_id)
            return self._run_summary(record)

    def get_run_config(self, run_id: str) -> dict[str, Any]:
        with self._session_factory() as session:
            record = self._require_run(session, run_id)
            return dict(record.config)

    def list_runs(self) -> list[RunSummary]:
        statement = select(RunRecord).order_by(RunRecord.created_at.desc())
        with self._session_factory() as session:
            records = session.exec(statement).all()
            return [self._run_summary(record) for record in records if record.config.get("purpose") != "manual_order"]

    def latest_completed_runs_by_symbol(
        self,
        symbols: list[str] | None = None,
        limit: int = 50,
    ) -> list[tuple[RunSummary, dict[str, Any] | None]]:
        """
        Return the most recent COMPLETED run per ticker, each paired with the
        payload of that run's latest ``decision.created`` event (or ``None``
        when the run produced no decision event).

        When ``symbols`` is provided, only those tickers are considered (and
        the result preserves the requested order); otherwise every distinct
        ticker with at least one completed run is returned, capped at
        ``limit``. Symbols are normalized to upper case.
        """

        requested = (
            [symbol.strip().upper() for symbol in symbols if symbol.strip()]
            if symbols is not None
            else None
        )
        statement = (
            select(RunRecord)
            .where(RunRecord.status == RunStatus.COMPLETED.value)
            .order_by(RunRecord.created_at.desc())
        )
        if requested:
            statement = statement.where(RunRecord.ticker.in_(requested))
        with self._session_factory() as session:
            records = session.exec(statement).all()
            latest_by_ticker: dict[str, RunRecord] = {}
            for record in records:
                if record.config.get("purpose") == "manual_order":
                    continue
                if record.ticker not in latest_by_ticker:
                    latest_by_ticker[record.ticker] = record
                if requested is None and len(latest_by_ticker) >= limit:
                    break

            ordered = (
                [latest_by_ticker[symbol] for symbol in requested if symbol in latest_by_ticker]
                if requested
                else list(latest_by_ticker.values())
            )
            results: list[tuple[RunSummary, dict[str, Any] | None]] = []
            for record in ordered:
                event_statement = (
                    select(RunEventRecord)
                    .where(RunEventRecord.run_id == record.run_id)
                    .where(RunEventRecord.type == "decision.created")
                    .order_by(RunEventRecord.sequence.desc())
                    .limit(1)
                )
                event = session.exec(event_statement).first()
                payload = dict(event.payload) if event is not None else None
                results.append((self._run_summary(record), payload))
            return results

    def create_report_schedule(
        self,
        *,
        name: str,
        symbol: str,
        cadence: str,
        broker_mode: str,
        execution_mode: str,
        enabled: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> ReportScheduleRecord:
        if not name.strip():
            raise ValueError("schedule name is required")
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("schedule symbol is required")
        if cadence not in {"market_open", "every_5_min", "hourly", "daily", "manual"}:
            raise ValueError("unsupported schedule cadence")
        if broker_mode not in {"disabled", "paper", "live_preview"}:
            raise ValueError("unsupported broker mode")
        if execution_mode not in {"real", "simulated"}:
            raise ValueError("unsupported execution mode")
        record = ReportScheduleRecord(
            name=name.strip(),
            symbol=normalized_symbol,
            cadence=cadence,
            broker_mode=broker_mode,
            execution_mode=execution_mode,
            enabled=enabled,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_report_schedule(record)

    def list_report_schedules(
        self,
        *,
        symbol: str | None = None,
        enabled: bool | None = None,
    ) -> list[ReportScheduleRecord]:
        statement = select(ReportScheduleRecord).order_by(ReportScheduleRecord.created_at.desc())
        if symbol is not None:
            statement = statement.where(ReportScheduleRecord.symbol == symbol.strip().upper())
        if enabled is not None:
            statement = statement.where(ReportScheduleRecord.enabled == enabled)
        with self._session_factory() as session:
            return [self._detach_report_schedule(record) for record in session.exec(statement).all()]

    def get_report_schedule(self, schedule_id: str) -> ReportScheduleRecord:
        with self._session_factory() as session:
            record = session.get(ReportScheduleRecord, schedule_id)
            if record is None:
                raise KeyError(schedule_id)
            return self._detach_report_schedule(record)

    def mark_report_schedule_run(
        self,
        schedule_id: str,
        run_id: str,
    ) -> ReportScheduleRecord:
        now = now_utc()
        with self._session_factory() as session:
            record = session.get(ReportScheduleRecord, schedule_id)
            if record is None:
                raise KeyError(schedule_id)
            self._require_run(session, run_id)
            record.last_run_id = run_id
            record.last_ran_at = now
            record.updated_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_report_schedule(record)

    def set_run_status(self, run_id: str, status: RunStatus | str) -> RunSummary:
        with self._session_factory() as session:
            record = self._require_run(session, run_id)
            record.status = status.value if isinstance(status, RunStatus) else status
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._run_summary(record)

    def append_event(self, event: RunEvent) -> RunEvent:
        record = RunEventRecord(
            run_id=event.run_id,
            sequence=event.sequence,
            type=event.type,
            node=event.node,
            message=event.message,
            payload=event.payload,
            created_at=event.created_at,
        )
        with self._session_factory() as session:
            self._require_run(session, event.run_id)
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._run_event(record)

    def list_events(self, run_id: str) -> list[RunEvent]:
        statement = (
            select(RunEventRecord)
            .where(RunEventRecord.run_id == run_id)
            .order_by(RunEventRecord.sequence)
        )
        with self._session_factory() as session:
            self._require_run(session, run_id)
            records = session.exec(statement).all()
            return [self._run_event(record) for record in records]

    def list_events_since(
        self, run_id: str, *, after_sequence: int = 0
    ) -> list[RunEvent]:
        """Return events for ``run_id`` with sequence > ``after_sequence``.

        Used by the live SSE stream to tail events incrementally without
        re-sending the entire history on every poll.
        """
        statement = (
            select(RunEventRecord)
            .where(RunEventRecord.run_id == run_id)
            .where(RunEventRecord.sequence > after_sequence)
            .order_by(RunEventRecord.sequence)
        )
        with self._session_factory() as session:
            self._require_run(session, run_id)
            records = session.exec(statement).all()
            return [self._run_event(record) for record in records]

    def start_observability_trace(
        self,
        *,
        run_id: str,
        provider: str = "local",
        external_trace_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ObservabilityTraceRecord:
        with self._session_factory() as session:
            self._require_run(session, run_id)
            record = ObservabilityTraceRecord(
                run_id=run_id,
                provider=provider,
                status="running",
                external_trace_id=external_trace_id,
                metadata_payload=metadata or {},
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_observability_trace(record)

    def update_observability_trace(
        self,
        run_id: str,
        *,
        status: str,
        provider: str | None = None,
        metadata: dict[str, Any] | None = None,
        cost: dict[str, Any] | None = None,
        external_trace_id: str | None = None,
    ) -> ObservabilityTraceRecord:
        with self._session_factory() as session:
            record = self._require_observability_trace(session, run_id)
            record.status = status
            if provider is not None:
                record.provider = provider
            if metadata:
                record.metadata_payload = {
                    **dict(record.metadata_payload),
                    **metadata,
                }
            if cost:
                record.cost = {**dict(record.cost), **cost}
            if external_trace_id is not None:
                record.external_trace_id = external_trace_id
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_observability_trace(record)

    def get_observability_trace(self, run_id: str) -> ObservabilityTraceRecord:
        with self._session_factory() as session:
            record = self._require_observability_trace(session, run_id)
            return self._detach_observability_trace(record)

    def list_observability_traces(self) -> list[ObservabilityTraceRecord]:
        statement = select(ObservabilityTraceRecord).order_by(
            ObservabilityTraceRecord.created_at.desc()
        )
        with self._session_factory() as session:
            return [
                self._detach_observability_trace(record)
                for record in session.exec(statement).all()
            ]

    def store_decision(
        self,
        run_id: str,
        rating: str,
        action: str,
        thesis: str,
        risk_notes: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> DecisionRecord:
        with self._session_factory() as session:
            run = self._require_run(session, run_id)
            record = DecisionRecord(
                run_id=run_id,
                rating=rating,
                action=action,
                thesis=thesis,
                risk_notes=risk_notes,
                payload=payload or {},
            )
            run.final_rating = rating
            run.final_action = action
            run.updated_at = now_utc()
            session.add(record)
            session.add(run)
            session.commit()
            session.refresh(record)
            return record

    def append_private_office_event(
        self,
        *,
        event_type: str,
        summary: str,
        actor: str,
        entity_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> PrivateOfficeEventRecord:
        record = PrivateOfficeEventRecord(
            event_type=event_type,
            summary=summary,
            actor=actor,
            entity_id=entity_id,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_private_office_event(record)

    def list_private_office_events(
        self,
        *,
        entity_id: str | None = None,
    ) -> list[PrivateOfficeEventRecord]:
        statement = select(PrivateOfficeEventRecord).order_by(PrivateOfficeEventRecord.created_at)
        if entity_id is not None:
            statement = statement.where(PrivateOfficeEventRecord.entity_id == entity_id)
        with self._session_factory() as session:
            return [self._detach_private_office_event(record) for record in session.exec(statement).all()]

    def upsert_private_office_entity(
        self,
        *,
        entity_id: str,
        entity_type: str,
        label: str,
        external_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> PrivateOfficeEntityRecord:
        with self._session_factory() as session:
            record = session.get(PrivateOfficeEntityRecord, entity_id)
            if record is None:
                record = PrivateOfficeEntityRecord(
                    entity_id=entity_id,
                    entity_type=entity_type,
                    label=label,
                    external_id=external_id,
                    payload=payload or {},
                )
            else:
                record.entity_type = entity_type
                record.label = label
                record.external_id = external_id
                record.payload = payload or {}
                record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_private_office_entity(record)

    def get_private_office_entity(self, entity_id: str) -> PrivateOfficeEntityRecord:
        with self._session_factory() as session:
            record = session.get(PrivateOfficeEntityRecord, entity_id)
            if record is None:
                raise KeyError(entity_id)
            return self._detach_private_office_entity(record)

    def list_private_office_entities(
        self,
        *,
        entity_type: str | None = None,
    ) -> list[PrivateOfficeEntityRecord]:
        statement = select(PrivateOfficeEntityRecord).order_by(PrivateOfficeEntityRecord.created_at)
        if entity_type is not None:
            statement = statement.where(PrivateOfficeEntityRecord.entity_type == entity_type)
        with self._session_factory() as session:
            return [self._detach_private_office_entity(record) for record in session.exec(statement).all()]

    def link_private_office_entities(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relationship: str,
        payload: dict[str, Any] | None = None,
    ) -> PrivateOfficeEdgeRecord:
        with self._session_factory() as session:
            self._require_private_office_entity(session, source_entity_id)
            self._require_private_office_entity(session, target_entity_id)
            record = PrivateOfficeEdgeRecord(
                source_entity_id=source_entity_id,
                target_entity_id=target_entity_id,
                relationship=relationship,
                payload=payload or {},
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_private_office_edge(record)

    def list_private_office_edges(
        self,
        *,
        source_entity_id: str | None = None,
        target_entity_id: str | None = None,
    ) -> list[PrivateOfficeEdgeRecord]:
        statement = select(PrivateOfficeEdgeRecord).order_by(PrivateOfficeEdgeRecord.created_at)
        if source_entity_id is not None:
            statement = statement.where(PrivateOfficeEdgeRecord.source_entity_id == source_entity_id)
        if target_entity_id is not None:
            statement = statement.where(PrivateOfficeEdgeRecord.target_entity_id == target_entity_id)
        with self._session_factory() as session:
            return [self._detach_private_office_edge(record) for record in session.exec(statement).all()]

    def create_portfolio_mandate(
        self,
        *,
        name: str,
        control_mode: str,
        account_ref: str,
        funding_limit: float,
        max_position_percent: float,
        max_drawdown_percent: float,
        daily_turnover_limit_percent: float,
        paper_mode_required: bool,
        kill_switch_enabled: bool,
        status: str = "draft",
        payload: dict[str, Any] | None = None,
    ) -> PortfolioMandateRecord:
        self._validate_portfolio_mandate(
            control_mode=control_mode,
            funding_limit=funding_limit,
            max_position_percent=max_position_percent,
            max_drawdown_percent=max_drawdown_percent,
            daily_turnover_limit_percent=daily_turnover_limit_percent,
            paper_mode_required=paper_mode_required,
            kill_switch_enabled=kill_switch_enabled,
        )
        record = PortfolioMandateRecord(
            name=name,
            control_mode=control_mode,
            account_ref=account_ref,
            funding_limit=funding_limit,
            max_position_percent=max_position_percent,
            max_drawdown_percent=max_drawdown_percent,
            daily_turnover_limit_percent=daily_turnover_limit_percent,
            paper_mode_required=paper_mode_required,
            kill_switch_enabled=kill_switch_enabled,
            status=status,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_portfolio_mandate(record)

    def list_portfolio_mandates(
        self,
        *,
        control_mode: str | None = None,
    ) -> list[PortfolioMandateRecord]:
        statement = select(PortfolioMandateRecord).order_by(PortfolioMandateRecord.created_at)
        if control_mode is not None:
            statement = statement.where(PortfolioMandateRecord.control_mode == control_mode)
        with self._session_factory() as session:
            return [self._detach_portfolio_mandate(record) for record in session.exec(statement).all()]

    def create_agent_workflow(
        self,
        *,
        name: str,
        agent_class: str,
        graph_runtime: str,
        status: str,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        required_provider_roles: dict[str, str],
        payload: dict[str, Any] | None = None,
    ) -> AgentWorkflowRecord:
        self._validate_agent_workflow(
            name=name,
            agent_class=agent_class,
            graph_runtime=graph_runtime,
            nodes=nodes,
            required_provider_roles=required_provider_roles,
        )
        record = AgentWorkflowRecord(
            name=name,
            agent_class=agent_class,
            graph_runtime=graph_runtime,
            status=status,
            nodes=nodes,
            edges=edges,
            required_provider_roles=required_provider_roles,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_agent_workflow(record)

    def list_agent_workflows(
        self,
        *,
        agent_class: str | None = None,
    ) -> list[AgentWorkflowRecord]:
        statement = select(AgentWorkflowRecord).order_by(AgentWorkflowRecord.created_at.desc())
        if agent_class is not None:
            statement = statement.where(AgentWorkflowRecord.agent_class == agent_class)
        with self._session_factory() as session:
            return [self._detach_agent_workflow(record) for record in session.exec(statement).all()]

    def create_agent_operation(
        self,
        *,
        agent_id: str,
        agent_name: str,
        room_id: str,
        symbol: str,
        operation_type: str,
        authority: str,
        source_workflow_id: str | None = None,
        linked_run_id: str | None = None,
        linked_execution_program_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentOperationRecord:
        normalized_symbol = self._normalize_required_symbol(symbol, "agent operation symbol")
        normalized_operation_type = operation_type.strip()
        normalized_authority = authority.strip()
        self._validate_agent_operation(
            agent_id=agent_id,
            agent_name=agent_name,
            room_id=room_id,
            operation_type=normalized_operation_type,
            status="queued",
            authority=normalized_authority,
        )
        record = AgentOperationRecord(
            agent_id=agent_id.strip(),
            agent_name=agent_name.strip(),
            room_id=room_id.strip(),
            symbol=normalized_symbol,
            operation_type=normalized_operation_type,
            status="queued",
            authority=normalized_authority,
            source_workflow_id=source_workflow_id,
            linked_run_id=linked_run_id,
            linked_execution_program_id=linked_execution_program_id,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_agent_operation(record)

    def list_agent_operations(
        self,
        *,
        limit: int | None = None,
        agent_id: str | None = None,
        room_id: str | None = None,
        symbol: str | None = None,
        operation_type: str | None = None,
        status: str | None = None,
        authority: str | None = None,
    ) -> list[AgentOperationRecord]:
        statement = select(AgentOperationRecord).order_by(
            AgentOperationRecord.created_at.desc()
        )
        if agent_id is not None:
            statement = statement.where(AgentOperationRecord.agent_id == agent_id)
        if room_id is not None:
            statement = statement.where(AgentOperationRecord.room_id == room_id)
        if symbol is not None:
            statement = statement.where(
                AgentOperationRecord.symbol == symbol.strip().upper()
            )
        if operation_type is not None:
            statement = statement.where(AgentOperationRecord.operation_type == operation_type)
        if status is not None:
            statement = statement.where(AgentOperationRecord.status == status)
        if authority is not None:
            statement = statement.where(AgentOperationRecord.authority == authority)
        if limit is not None:
            statement = statement.limit(max(0, limit))
        with self._session_factory() as session:
            return [
                self._detach_agent_operation(record)
                for record in session.exec(statement).all()
            ]

    def update_agent_operation(
        self,
        operation_id: str,
        *,
        status: str,
        linked_run_id: str | None = None,
        linked_execution_program_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> AgentOperationRecord:
        normalized_status = status.strip()
        if normalized_status not in self._AGENT_OPERATION_STATUSES:
            raise ValueError("agent operation status must be queued, running, completed, or failed")
        with self._session_factory() as session:
            record = session.get(AgentOperationRecord, operation_id)
            if record is None:
                raise KeyError(operation_id)
            self._validate_agent_operation(
                agent_id=record.agent_id,
                agent_name=record.agent_name,
                room_id=record.room_id,
                operation_type=record.operation_type,
                status=normalized_status,
                authority=record.authority,
            )
            record.status = normalized_status
            if linked_run_id is not None:
                record.linked_run_id = linked_run_id
            if linked_execution_program_id is not None:
                record.linked_execution_program_id = linked_execution_program_id
            if payload is not None:
                record.payload = payload
            now = now_utc()
            if normalized_status == "running" and record.started_at is None:
                record.started_at = now
            if normalized_status in {"completed", "failed"}:
                record.completed_at = now
            record.updated_at = now
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_agent_operation(record)

    def upsert_agent_pack(
        self,
        *,
        pack_id: str,
        source_url: str | None,
        source_commit: str | None,
        license: str | None,
        manifest: dict[str, Any],
        status: str = "imported",
    ) -> AgentPackRecord:
        if not pack_id.strip():
            raise ValueError("pack_id is required")
        with self._session_factory() as session:
            record = session.get(AgentPackRecord, pack_id)
            if record is None:
                record = AgentPackRecord(pack_id=pack_id)
            record.source_url = source_url
            record.source_commit = source_commit
            record.license = license
            record.manifest = manifest
            record.status = status
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_agent_pack(record)

    def list_agent_packs(self) -> list[AgentPackRecord]:
        statement = select(AgentPackRecord).order_by(AgentPackRecord.imported_at.desc())
        with self._session_factory() as session:
            return [self._detach_agent_pack(record) for record in session.exec(statement).all()]

    def upsert_imported_agent(
        self,
        *,
        agent_id: str,
        pack_id: str,
        source_slug: str,
        name: str,
        description: str,
        agent_class: str,
        system_prompt: str,
        guardrails: list[str],
        skills: list[str],
        commands: list[str],
        required_provider_roles: dict[str, str],
        required_connectors: list[str],
        tool_policy: dict[str, Any],
        output_schema: dict[str, Any],
        security_profile: dict[str, Any],
        status: str,
        payload: dict[str, Any],
    ) -> ImportedAgentRecord:
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        with self._session_factory() as session:
            record = session.get(ImportedAgentRecord, agent_id)
            if record is None:
                record = ImportedAgentRecord(
                    agent_id=agent_id,
                    pack_id=pack_id,
                    source_slug=source_slug,
                    name=name,
                    description=description,
                    agent_class=agent_class,
                    system_prompt=system_prompt,
                )
            record.pack_id = pack_id
            record.source_slug = source_slug
            record.name = name
            record.description = description
            record.agent_class = agent_class
            record.system_prompt = system_prompt
            record.guardrails = guardrails
            record.skills = skills
            record.commands = commands
            record.required_provider_roles = required_provider_roles
            record.required_connectors = required_connectors
            record.tool_policy = tool_policy
            record.output_schema = output_schema
            record.security_profile = security_profile
            record.status = status
            record.payload = payload
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_imported_agent(record)

    def list_imported_agents(
        self,
        *,
        pack_id: str | None = None,
        agent_class: str | None = None,
    ) -> list[ImportedAgentRecord]:
        statement = select(ImportedAgentRecord).order_by(ImportedAgentRecord.name)
        if pack_id is not None:
            statement = statement.where(ImportedAgentRecord.pack_id == pack_id)
        if agent_class is not None:
            statement = statement.where(ImportedAgentRecord.agent_class == agent_class)
        with self._session_factory() as session:
            return [self._detach_imported_agent(record) for record in session.exec(statement).all()]

    def upsert_imported_skill(
        self,
        *,
        skill_id: str,
        pack_id: str,
        source_path: str,
        name: str,
        description: str,
        instructions_markdown: str,
        references: list[str],
        scripts: list[str],
        artifact_requirements: dict[str, Any],
        status: str,
        payload: dict[str, Any],
    ) -> ImportedSkillRecord:
        if not skill_id.strip():
            raise ValueError("skill_id is required")
        with self._session_factory() as session:
            record = session.get(ImportedSkillRecord, skill_id)
            if record is None:
                record = ImportedSkillRecord(
                    skill_id=skill_id,
                    pack_id=pack_id,
                    source_path=source_path,
                    name=name,
                    description=description,
                    instructions_markdown=instructions_markdown,
                )
            record.pack_id = pack_id
            record.source_path = source_path
            record.name = name
            record.description = description
            record.instructions_markdown = instructions_markdown
            record.references = references
            record.scripts = scripts
            record.artifact_requirements = artifact_requirements
            record.status = status
            record.payload = payload
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_imported_skill(record)

    def list_imported_skills(
        self,
        *,
        pack_id: str | None = None,
    ) -> list[ImportedSkillRecord]:
        statement = select(ImportedSkillRecord).order_by(ImportedSkillRecord.name)
        if pack_id is not None:
            statement = statement.where(ImportedSkillRecord.pack_id == pack_id)
        with self._session_factory() as session:
            return [self._detach_imported_skill(record) for record in session.exec(statement).all()]

    def upsert_mcp_connector(
        self,
        *,
        connector_id: str,
        name: str,
        url: str,
        provider_id: str | None,
        capabilities: list[str],
        health: dict[str, Any],
        enabled: bool,
        subscription_required: bool,
        payload: dict[str, Any],
        required_secret_ref: str | None = None,
    ) -> McpConnectorRecord:
        if not connector_id.strip():
            raise ValueError("connector_id is required")
        with self._session_factory() as session:
            record = session.get(McpConnectorRecord, connector_id)
            if record is None:
                record = McpConnectorRecord(
                    connector_id=connector_id,
                    name=name,
                    url=url,
                )
            record.name = name
            record.url = url
            record.provider_id = provider_id
            record.required_secret_ref = required_secret_ref
            record.capabilities = capabilities
            record.health = health
            record.enabled = enabled
            record.subscription_required = subscription_required
            record.payload = payload
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_mcp_connector(record)

    def list_mcp_connectors(self) -> list[McpConnectorRecord]:
        statement = select(McpConnectorRecord).order_by(McpConnectorRecord.connector_id)
        with self._session_factory() as session:
            return [self._detach_mcp_connector(record) for record in session.exec(statement).all()]

    def store_snapshot_manifest(
        self,
        *,
        snapshot_id: str,
        storage_profile: str,
        encryption_mode: str,
        offsite_target: str | None,
        manifest: dict[str, Any],
    ) -> SnapshotManifestRecord:
        record = SnapshotManifestRecord(
            snapshot_id=snapshot_id,
            storage_profile=storage_profile,
            encryption_mode=encryption_mode,
            offsite_target=offsite_target,
            manifest=manifest,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_snapshot_manifest(record)

    def list_snapshot_manifests(self) -> list[SnapshotManifestRecord]:
        statement = select(SnapshotManifestRecord).order_by(SnapshotManifestRecord.created_at.desc())
        with self._session_factory() as session:
            return [self._detach_snapshot_manifest(record) for record in session.exec(statement).all()]

    def get_snapshot_manifest(self, snapshot_id: str) -> SnapshotManifestRecord:
        with self._session_factory() as session:
            record = session.get(SnapshotManifestRecord, snapshot_id)
            if record is None:
                raise KeyError(snapshot_id)
            return self._detach_snapshot_manifest(record)

    def store_market_data_snapshot(
        self,
        *,
        provider_id: str,
        symbol: str,
        snapshot_kind: str,
        feed: str | None = None,
        timeframe: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> MarketDataSnapshotRecord:
        record = MarketDataSnapshotRecord(
            provider_id=provider_id,
            symbol=symbol.upper(),
            snapshot_kind=snapshot_kind,
            feed=feed,
            timeframe=timeframe,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_market_data_snapshot(record)

    def list_market_data_snapshots(
        self,
        *,
        provider_id: str | None = None,
        symbol: str | None = None,
    ) -> list[MarketDataSnapshotRecord]:
        statement = select(MarketDataSnapshotRecord).order_by(MarketDataSnapshotRecord.created_at.desc())
        if provider_id is not None:
            statement = statement.where(MarketDataSnapshotRecord.provider_id == provider_id)
        if symbol is not None:
            statement = statement.where(MarketDataSnapshotRecord.symbol == symbol.upper())
        with self._session_factory() as session:
            return [self._detach_market_data_snapshot(record) for record in session.exec(statement).all()]

    def create_trade_intent(
        self,
        run_id: str,
        symbol: str,
        side: str,
        notional: float,
        order_type: str = "market",
        payload: dict[str, Any] | None = None,
    ) -> TradeIntentRecord:
        with self._session_factory() as session:
            self._require_run(session, run_id)
            record = TradeIntentRecord(
                run_id=run_id,
                symbol=symbol,
                side=side,
                notional=notional,
                order_type=order_type,
                payload=payload or {},
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def get_trade_intent(self, intent_id: str) -> TradeIntentRecord:
        with self._session_factory() as session:
            record = session.get(TradeIntentRecord, intent_id)
            if record is None:
                raise KeyError(intent_id)
            return record

    def mark_trade_intent_status(self, intent_id: str, status: str) -> str:
        """Set the intent's status and bump its updated_at.

        Used by the broker service when transitioning an intent without
        a corresponding broker order (e.g. operator-driven cancel before
        submission). Returns the new status so callers don't need to
        re-fetch.
        """

        with self._session_factory() as session:
            record = self._require_trade_intent(session, intent_id)
            record.status = status
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            return status

    # Status values that mean the trade is finished — exclude from "open" lists.
    _CLOSED_TRADE_STATUSES = (
        "filled",
        "canceled",
        "cancelled",
        "rejected",
        "expired",
        "done",
    )

    def list_open_trades(
        self,
        *,
        symbol: str | None = None,
        limit: int = 50,
    ) -> list[tuple[TradeIntentRecord, BrokerOrderRecord | None]]:
        """
        Return trade intents that are still in flight, paired with the latest
        broker order (if any). "Open" = status NOT IN the closed-set declared
        above. Most-recently-updated first.
        """

        with self._session_factory() as session:
            statement = (
                select(TradeIntentRecord)
                .where(TradeIntentRecord.status.notin_(self._CLOSED_TRADE_STATUSES))
                .order_by(TradeIntentRecord.updated_at.desc())
                .limit(limit)
            )
            if symbol:
                statement = statement.where(TradeIntentRecord.symbol == symbol.upper())
            intents = list(session.exec(statement).all())

            result: list[tuple[TradeIntentRecord, BrokerOrderRecord | None]] = []
            for intent in intents:
                order_statement = (
                    select(BrokerOrderRecord)
                    .where(BrokerOrderRecord.intent_id == intent.intent_id)
                    .order_by(BrokerOrderRecord.updated_at.desc())
                    .limit(1)
                )
                order = session.exec(order_statement).first()
                result.append((intent, order))
            return result

    def record_approval(
        self,
        intent_id: str,
        actor: str,
        action: str,
        before_payload: dict[str, Any],
        after_payload: dict[str, Any],
    ) -> ApprovalRecord:
        with self._session_factory() as session:
            self._require_trade_intent(session, intent_id)
            record = ApprovalRecord(
                intent_id=intent_id,
                actor=actor,
                action=action,
                before_payload=before_payload,
                after_payload=after_payload,
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def record_approval_ledger_entry(
        self,
        *,
        room_id: str,
        source: str,
        entity_type: str,
        entity_id: str,
        action: str,
        actor: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> ApprovalLedgerRecord:
        if action not in {"accept", "reject", "revise", "defer", "escalate"}:
            raise ValueError("approval ledger action must be accept, reject, revise, defer, or escalate")
        record = ApprovalLedgerRecord(
            room_id=room_id,
            source=source,
            entity_type=entity_type,
            entity_id=entity_id,
            action=action,
            actor=actor,
            summary=summary,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_approval_ledger_entry(record)

    def list_approval_ledger_entries(
        self,
        *,
        room_id: str | None = None,
        entity_id: str | None = None,
    ) -> list[ApprovalLedgerRecord]:
        statement = select(ApprovalLedgerRecord).order_by(ApprovalLedgerRecord.created_at.desc())
        if room_id is not None:
            statement = statement.where(ApprovalLedgerRecord.room_id == room_id)
        if entity_id is not None:
            statement = statement.where(ApprovalLedgerRecord.entity_id == entity_id)
        with self._session_factory() as session:
            return [self._detach_approval_ledger_entry(record) for record in session.exec(statement).all()]

    def create_agent_trigger(
        self,
        *,
        name: str,
        room_id: str,
        trigger_type: str,
        target_agent: str,
        symbol: str | None = None,
        condition: dict[str, Any] | None = None,
        workflow_id: str | None = None,
        enabled: bool = True,
        payload: dict[str, Any] | None = None,
    ) -> AgentTriggerRecord:
        if not name.strip():
            raise ValueError("trigger name is required")
        if not trigger_type.strip():
            raise ValueError("trigger type is required")
        if not target_agent.strip():
            raise ValueError("target agent is required")
        record = AgentTriggerRecord(
            name=name.strip(),
            room_id=room_id,
            trigger_type=trigger_type.strip(),
            target_agent=target_agent.strip(),
            symbol=symbol.strip().upper() if symbol else None,
            condition=condition or {},
            workflow_id=workflow_id,
            enabled=enabled,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_agent_trigger(record)

    def list_agent_triggers(
        self,
        *,
        room_id: str | None = None,
        symbol: str | None = None,
        enabled: bool | None = None,
    ) -> list[AgentTriggerRecord]:
        statement = select(AgentTriggerRecord).order_by(AgentTriggerRecord.created_at.desc())
        if room_id is not None:
            statement = statement.where(AgentTriggerRecord.room_id == room_id)
        if symbol is not None:
            statement = statement.where(AgentTriggerRecord.symbol == symbol.strip().upper())
        if enabled is not None:
            statement = statement.where(AgentTriggerRecord.enabled == enabled)
        with self._session_factory() as session:
            return [self._detach_agent_trigger(record) for record in session.exec(statement).all()]

    def create_trade_thesis(
        self,
        *,
        symbol: str,
        source_report_id: str | None = None,
        source_room: str = "research",
        target_room: str = "market",
        direction: str,
        horizon: str,
        conviction: float,
        thesis: str,
        catalysts: list[str] | None = None,
        invalidation: list[str] | None = None,
        risk_notes: str | None = None,
        status: str = "proposed",
        payload: dict[str, Any] | None = None,
    ) -> TradeThesisRecord:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("trade thesis symbol is required")
        if source_room != "research":
            raise ValueError("trade theses must originate from the research room")
        if target_room != "market":
            raise ValueError("trade theses must hand off to the brokerage floor")
        if direction not in {"long", "short", "neutral", "hedge", "exit"}:
            raise ValueError("unsupported trade thesis direction")
        if not horizon.strip():
            raise ValueError("trade thesis horizon is required")
        if not thesis.strip():
            raise ValueError("trade thesis body is required")
        if not 0 <= conviction <= 1:
            raise ValueError("trade thesis conviction must be between 0 and 1")
        if status not in {"proposed", "accepted", "rejected", "revised", "deferred", "sent_to_broker"}:
            raise ValueError("unsupported trade thesis status")
        record = TradeThesisRecord(
            symbol=normalized_symbol,
            source_report_id=source_report_id,
            source_room=source_room,
            target_room=target_room,
            direction=direction,
            horizon=horizon.strip(),
            conviction=conviction,
            status=status,
            thesis=thesis.strip(),
            catalysts=catalysts or [],
            invalidation=invalidation or [],
            risk_notes=risk_notes,
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_trade_thesis(record)

    def list_trade_theses(
        self,
        *,
        symbol: str | None = None,
        status: str | None = None,
        target_room: str | None = None,
    ) -> list[TradeThesisRecord]:
        statement = select(TradeThesisRecord).order_by(TradeThesisRecord.created_at.desc())
        if symbol is not None:
            statement = statement.where(TradeThesisRecord.symbol == symbol.strip().upper())
        if status is not None:
            statement = statement.where(TradeThesisRecord.status == status)
        if target_room is not None:
            statement = statement.where(TradeThesisRecord.target_room == target_room)
        with self._session_factory() as session:
            return [self._detach_trade_thesis(record) for record in session.exec(statement).all()]

    def create_portfolio_review(
        self,
        *,
        symbol: str,
        room_id: str = "portfolio",
        status: str = "draft",
        goals: str | None = None,
        horizon: str | None = None,
        risk_posture: str | None = None,
        sector_focus: str | None = None,
        constraints: str | None = None,
        liquidity_needs: str | None = None,
        thesis: dict[str, Any] | None = None,
        missing_provider_facts: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> PortfolioReviewRecord:
        normalized_symbol = self._normalize_required_symbol(symbol, "portfolio review symbol")
        record = PortfolioReviewRecord(
            symbol=normalized_symbol,
            room_id=room_id,
            status=status,
            goals=goals,
            horizon=horizon,
            risk_posture=risk_posture,
            sector_focus=sector_focus,
            constraints=constraints,
            liquidity_needs=liquidity_needs,
            thesis=thesis or {},
            missing_provider_facts=missing_provider_facts or [],
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_portfolio_review(record)

    def list_portfolio_reviews(
        self,
        *,
        limit: int | None = None,
        symbol: str | None = None,
        status: str | None = None,
    ) -> list[PortfolioReviewRecord]:
        statement = select(PortfolioReviewRecord).order_by(PortfolioReviewRecord.created_at.desc())
        if symbol is not None:
            statement = statement.where(
                PortfolioReviewRecord.symbol == symbol.strip().upper()
            )
        if status is not None:
            statement = statement.where(PortfolioReviewRecord.status == status)
        if limit is not None:
            statement = statement.limit(max(0, limit))
        with self._session_factory() as session:
            return [self._detach_portfolio_review(record) for record in session.exec(statement).all()]

    def create_funding_allocation_review(
        self,
        *,
        symbol: str,
        source_thesis_id: str | None = None,
        execution_program_id: str | None = None,
        status: str = "draft",
        notional: float | None = None,
        tracks: list[dict[str, Any]] | None = None,
        missing_provider_facts: list[str] | None = None,
        approval_next_steps: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> FundingAllocationReviewRecord:
        normalized_symbol = self._normalize_required_symbol(
            symbol,
            "funding allocation review symbol",
        )
        if notional is not None and notional <= 0:
            raise ValueError("funding allocation notional must be greater than zero")
        record = FundingAllocationReviewRecord(
            symbol=normalized_symbol,
            source_thesis_id=source_thesis_id,
            execution_program_id=execution_program_id,
            status=status,
            notional=notional,
            tracks=tracks or [],
            missing_provider_facts=missing_provider_facts or [],
            approval_next_steps=approval_next_steps or [],
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_funding_allocation_review(record)

    def list_funding_allocation_reviews(
        self,
        *,
        limit: int | None = None,
        symbol: str | None = None,
        status: str | None = None,
    ) -> list[FundingAllocationReviewRecord]:
        statement = select(FundingAllocationReviewRecord).order_by(
            FundingAllocationReviewRecord.created_at.desc()
        )
        if symbol is not None:
            statement = statement.where(
                FundingAllocationReviewRecord.symbol == symbol.strip().upper()
            )
        if status is not None:
            statement = statement.where(FundingAllocationReviewRecord.status == status)
        if limit is not None:
            statement = statement.limit(max(0, limit))
        with self._session_factory() as session:
            return [
                self._detach_funding_allocation_review(record)
                for record in session.exec(statement).all()
            ]

    def create_execution_program(
        self,
        *,
        symbol: str,
        algorithm: str,
        source_thesis_id: str | None = None,
        state: str = "preview_ready",
        mode: str = "paper",
        approval_status: str = "required",
        live_submission_enabled: bool = False,
        trigger_points: list[dict[str, Any]] | None = None,
        circuit_breakers: list[dict[str, Any]] | None = None,
        missing_provider_facts: list[str] | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ExecutionProgramRecord:
        normalized_symbol = self._normalize_required_symbol(symbol, "execution program symbol")
        if not algorithm.strip():
            raise ValueError("execution program algorithm is required")
        if mode != "paper":
            raise ValueError("execution program mode must be paper")
        if live_submission_enabled:
            raise ValueError("live_submission_enabled is not supported yet")
        record = ExecutionProgramRecord(
            symbol=normalized_symbol,
            source_thesis_id=source_thesis_id,
            algorithm=algorithm.strip(),
            state=state,
            mode=mode,
            approval_status=approval_status,
            live_submission_enabled=False,
            trigger_points=trigger_points or [],
            circuit_breakers=circuit_breakers or [],
            missing_provider_facts=missing_provider_facts or [],
            payload=payload or {},
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_execution_program(record)

    def list_execution_programs(
        self,
        *,
        limit: int | None = None,
        symbol: str | None = None,
        state: str | None = None,
    ) -> list[ExecutionProgramRecord]:
        statement = select(ExecutionProgramRecord).order_by(
            ExecutionProgramRecord.created_at.desc()
        )
        if symbol is not None:
            statement = statement.where(
                ExecutionProgramRecord.symbol == symbol.strip().upper()
            )
        if state is not None:
            statement = statement.where(ExecutionProgramRecord.state == state)
        if limit is not None:
            statement = statement.limit(max(0, limit))
        with self._session_factory() as session:
            return [self._detach_execution_program(record) for record in session.exec(statement).all()]

    def append_execution_program_event(
        self,
        *,
        program_id: str,
        event_type: str,
        summary: str,
        payload: dict[str, Any] | None = None,
    ) -> ExecutionProgramEventRecord:
        if not event_type.strip():
            raise ValueError("execution program event_type is required")
        if not summary.strip():
            raise ValueError("execution program event summary is required")
        with self._session_factory() as session:
            self._require_execution_program(session, program_id)
            record = ExecutionProgramEventRecord(
                program_id=program_id,
                event_type=event_type.strip(),
                summary=summary.strip(),
                payload=payload or {},
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_execution_program_event(record)

    def list_execution_program_events(
        self,
        program_id: str,
    ) -> list[ExecutionProgramEventRecord]:
        statement = (
            select(ExecutionProgramEventRecord)
            .where(ExecutionProgramEventRecord.program_id == program_id)
            .order_by(ExecutionProgramEventRecord.created_at)
        )
        with self._session_factory() as session:
            self._require_execution_program(session, program_id)
            return [
                self._detach_execution_program_event(record)
                for record in session.exec(statement).all()
            ]

    def has_approval(self, intent_id: str, action: str = "approve_order") -> bool:
        relevant_actions = {
            "approve_order",
            "reject_order",
            "revoke_order",
            "cancel_order",
        }
        relevant_actions.add(action)
        statement = (
            select(ApprovalRecord)
            .where(ApprovalRecord.intent_id == intent_id)
            .where(ApprovalRecord.action.in_(relevant_actions))
            .order_by(ApprovalRecord.created_at.desc())
            .limit(1)
        )
        with self._session_factory() as session:
            record = session.exec(statement).first()
            if record is None:
                return False
            return record.after_payload.get("status") == "approved"

    def store_broker_order(
        self,
        intent_id: str,
        broker: str,
        environment: str,
        status: str,
        broker_order_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> BrokerOrderRecord:
        with self._session_factory() as session:
            trade_intent = self._require_trade_intent(session, intent_id)
            record = BrokerOrderRecord(
                intent_id=intent_id,
                broker=broker,
                environment=environment,
                status=status,
                broker_order_id=broker_order_id,
                payload=payload or {},
            )
            trade_intent.status = status
            trade_intent.updated_at = now_utc()
            session.add(record)
            session.add(trade_intent)
            session.commit()
            session.refresh(record)
            return record

    def list_provider_configs(self) -> list[ProviderConfigRecord]:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            statement = select(ProviderConfigRecord).order_by(ProviderConfigRecord.provider_id)
            return list(session.exec(statement).all())

    def get_provider_config(self, provider_id: str) -> ProviderConfigRecord:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            record = session.get(ProviderConfigRecord, provider_id)
            if record is None:
                raise KeyError(provider_id)
            return record

    def create_user_provider(
        self,
        *,
        name: str,
        kind: str,
        base_url: str,
        model: str,
        api_key_env: str | None = None,
        role_models: dict[str, Any] | None = None,
    ) -> ProviderConfigRecord:
        """Create a user-defined LLM provider.

        ``kind`` controls the wire protocol:

        * ``"openai-compatible"`` -- routes through the existing
          ``OpenAIClient`` (chat completions), targeting any OpenAI-shape
          gateway: GLM, Kimi, OpenRouter passthroughs, vLLM, etc.
        * ``"anthropic-compatible"`` -- routes through ``AnthropicClient``
          with a custom base URL.

        ``base_url`` and ``model`` are required and user-supplied.
        ``api_key_env`` is the name of a secret reference (e.g.
        ``"env:ZHIPU_API_KEY"`` or ``"keychain:kimi:default"``) -- when
        provided, ``auth_required`` is set to True; when omitted, the
        provider is wired as anonymous (suitable for local servers).

        The new record's ``config.user_defined`` is set to ``True`` so
        the API layer can distinguish user records from built-ins for
        edit/delete authority.
        """
        cleaned_name = name.strip()
        if not cleaned_name:
            raise ValueError("provider name is required")
        if kind not in {"openai-compatible", "anthropic-compatible"}:
            raise ValueError(
                "provider kind must be 'openai-compatible' or 'anthropic-compatible'"
            )
        cleaned_base_url = base_url.strip()
        if not cleaned_base_url:
            raise ValueError("base_url is required")
        cleaned_model = model.strip()
        if not cleaned_model:
            raise ValueError("model is required")

        provider_id = self._user_provider_id_for(cleaned_name)
        # Map the public "kind" onto the factory's provider identifier.
        # Anthropic-compatible custom URLs still route through the
        # AnthropicClient, which already accepts base_url.
        factory_provider = (
            "openai-compatible" if kind == "openai-compatible" else "anthropic"
        )
        capability_tag = (
            "openai-compatible" if kind == "openai-compatible" else "anthropic-compatible"
        )

        config: dict[str, Any] = {
            "user_defined": True,
            "kind": kind,
            "provider": factory_provider,
            "base_url": cleaned_base_url,
            "model": cleaned_model,
            "auth_required": bool(api_key_env),
            "runner_supported": True,
            "graph_runner_supported": True,
        }
        if role_models is not None:
            config["role_models"] = role_models

        with self._session_factory() as session:
            self._seed_provider_configs(session)
            existing = session.get(ProviderConfigRecord, provider_id)
            if existing is not None:
                raise ValueError(
                    f"a provider named {cleaned_name!r} already exists"
                )
            record = ProviderConfigRecord(
                provider_id=provider_id,
                name=cleaned_name,
                role="llm",
                status="needs_key" if api_key_env else "available",
                capabilities=[capability_tag, "user-defined", "tool-calling"],
                primary_use=f"User-defined {kind} provider at {cleaned_base_url}.",
                control_surface="platform",
                write_authority="none",
                enabled=False,
                secret_ref=api_key_env,
                config=config,
                health={"status": "not_checked"},
            )
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def delete_user_provider(self, provider_id: str) -> None:
        """Delete a user-defined provider.

        Refuses to delete built-in providers (those defined in
        ``PROVIDERS``) and refuses to delete a provider that is
        currently wired into any role assignment -- the caller should
        rebind those roles first.
        """
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            record = session.get(ProviderConfigRecord, provider_id)
            if record is None:
                raise KeyError(provider_id)
            if not record.config.get("user_defined"):
                raise ValueError("only user-defined providers can be deleted")
            assignments = session.exec(
                select(ProviderRoleAssignmentRecord).where(
                    ProviderRoleAssignmentRecord.provider_id == provider_id
                )
            ).all()
            if assignments:
                bound_roles = ", ".join(a.role_key for a in assignments)
                raise ValueError(
                    f"cannot delete provider while bound to roles: {bound_roles}"
                )
            session.delete(record)
            session.commit()

    @staticmethod
    def _user_provider_id_for(name: str) -> str:
        slug_chars = []
        for ch in name.lower():
            if ch.isalnum():
                slug_chars.append(ch)
            elif slug_chars and slug_chars[-1] != "-":
                slug_chars.append("-")
        slug = "".join(slug_chars).strip("-")
        if not slug:
            raise ValueError("provider name must contain alphanumeric characters")
        return f"user:{slug}"

    def upsert_provider_config(
        self,
        provider_id: str,
        *,
        enabled: bool | None = None,
        secret_ref: str | None = None,
        config: dict[str, Any] | None = None,
        health: dict[str, Any] | None = None,
        status: str | None = None,
        clear_secret_ref: bool = False,
    ) -> ProviderConfigRecord:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            record = session.get(ProviderConfigRecord, provider_id)
            descriptor = provider_descriptor_by_id(provider_id)
            if record is None and descriptor is None:
                raise KeyError(provider_id)
            if record is None and descriptor is not None:
                record = self._provider_config_from_descriptor(descriptor)
            previously_user_defined = bool(record.config.get("user_defined"))
            if enabled is not None:
                record.enabled = enabled
            if secret_ref is not None or clear_secret_ref:
                record.secret_ref = None if clear_secret_ref else secret_ref
                record.health = {"status": "not_checked"}
            if config is not None:
                sanitized = self._sanitize_config(config)
                # ``user_defined`` is an authority marker, not a
                # field the caller is allowed to set or clear via
                # config upserts -- it's owned by ``create_user_provider``
                # and ``delete_user_provider``.
                if previously_user_defined:
                    sanitized["user_defined"] = True
                else:
                    sanitized.pop("user_defined", None)
                record.config = sanitized
            if health is not None:
                record.health = self._sanitize_health(health)
            if status is not None:
                record.status = status
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

    def list_provider_role_assignments(self) -> list[ProviderRoleAssignmentRecord]:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            self._seed_provider_role_assignments(session)
            statement = select(ProviderRoleAssignmentRecord).order_by(
                ProviderRoleAssignmentRecord.role_key
            )
            return [
                self._detach_provider_role_assignment(record)
                for record in session.exec(statement).all()
            ]

    def upsert_provider_role_assignment(
        self,
        role_key: str,
        *,
        provider_id: str,
    ) -> ProviderRoleAssignmentRecord:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            self._seed_provider_role_assignments(session)
            # User-defined providers (created via ``create_user_provider``)
            # aren't in the built-in PROVIDERS tuple, so check the
            # ``ProviderConfigRecord`` table as well -- it's the source
            # of truth for "this provider exists and is wirable".
            if (
                provider_descriptor_by_id(provider_id) is None
                and session.get(ProviderConfigRecord, provider_id) is None
            ):
                raise KeyError(provider_id)
            default = next(
                (
                    assignment
                    for assignment in DEFAULT_PROVIDER_ROLE_ASSIGNMENTS
                    if assignment.role_key == role_key
                ),
                None,
            )
            if default is None:
                raise ValueError("Unknown provider role assignment")
            record = session.get(ProviderRoleAssignmentRecord, role_key)
            if record is None:
                record = ProviderRoleAssignmentRecord(
                    role_key=role_key,
                    provider_id=provider_id,
                    surface=default.surface,
                )
            else:
                record.provider_id = provider_id
                record.surface = default.surface
                record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_provider_role_assignment(record)

    @staticmethod
    def _run_summary(record: RunRecord) -> RunSummary:
        return RunSummary(
            run_id=record.run_id,
            ticker=record.ticker,
            trade_date=record.trade_date,
            status=record.status,
            final_rating=record.final_rating,
            final_action=record.final_action,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _run_event(record: RunEventRecord) -> RunEvent:
        return RunEvent(
            run_id=record.run_id,
            sequence=record.sequence,
            type=record.type,
            node=record.node,
            message=record.message,
            payload=record.payload,
            created_at=record.created_at,
        )

    @staticmethod
    def _detach_report_schedule(record: ReportScheduleRecord) -> ReportScheduleRecord:
        return ReportScheduleRecord(
            schedule_id=record.schedule_id,
            name=record.name,
            symbol=record.symbol,
            cadence=record.cadence,
            broker_mode=record.broker_mode,
            execution_mode=record.execution_mode,
            enabled=record.enabled,
            last_run_id=record.last_run_id,
            payload=dict(record.payload),
            last_ran_at=record.last_ran_at,
            next_run_at=record.next_run_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_approval_ledger_entry(record: ApprovalLedgerRecord) -> ApprovalLedgerRecord:
        return ApprovalLedgerRecord(
            approval_id=record.approval_id,
            room_id=record.room_id,
            source=record.source,
            entity_type=record.entity_type,
            entity_id=record.entity_id,
            action=record.action,
            actor=record.actor,
            summary=record.summary,
            payload=dict(record.payload),
            created_at=record.created_at,
        )

    @staticmethod
    def _detach_agent_trigger(record: AgentTriggerRecord) -> AgentTriggerRecord:
        return AgentTriggerRecord(
            trigger_id=record.trigger_id,
            name=record.name,
            room_id=record.room_id,
            trigger_type=record.trigger_type,
            target_agent=record.target_agent,
            symbol=record.symbol,
            condition=dict(record.condition),
            workflow_id=record.workflow_id,
            enabled=record.enabled,
            last_fired_at=record.last_fired_at,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_trade_thesis(record: TradeThesisRecord) -> TradeThesisRecord:
        return TradeThesisRecord(
            thesis_id=record.thesis_id,
            symbol=record.symbol,
            source_report_id=record.source_report_id,
            source_room=record.source_room,
            target_room=record.target_room,
            direction=record.direction,
            horizon=record.horizon,
            conviction=record.conviction,
            status=record.status,
            thesis=record.thesis,
            catalysts=list(record.catalysts),
            invalidation=list(record.invalidation),
            risk_notes=record.risk_notes,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_portfolio_review(record: PortfolioReviewRecord) -> PortfolioReviewRecord:
        return PortfolioReviewRecord(
            review_id=record.review_id,
            symbol=record.symbol,
            room_id=record.room_id,
            status=record.status,
            goals=record.goals,
            horizon=record.horizon,
            risk_posture=record.risk_posture,
            sector_focus=record.sector_focus,
            constraints=record.constraints,
            liquidity_needs=record.liquidity_needs,
            thesis=dict(record.thesis),
            missing_provider_facts=list(record.missing_provider_facts),
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_funding_allocation_review(
        record: FundingAllocationReviewRecord,
    ) -> FundingAllocationReviewRecord:
        return FundingAllocationReviewRecord(
            review_id=record.review_id,
            symbol=record.symbol,
            source_thesis_id=record.source_thesis_id,
            execution_program_id=record.execution_program_id,
            status=record.status,
            notional=record.notional,
            tracks=[dict(track) for track in record.tracks],
            missing_provider_facts=list(record.missing_provider_facts),
            approval_next_steps=list(record.approval_next_steps),
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_execution_program(record: ExecutionProgramRecord) -> ExecutionProgramRecord:
        return ExecutionProgramRecord(
            program_id=record.program_id,
            symbol=record.symbol,
            source_thesis_id=record.source_thesis_id,
            algorithm=record.algorithm,
            state=record.state,
            mode=record.mode,
            approval_status=record.approval_status,
            live_submission_enabled=record.live_submission_enabled,
            trigger_points=[dict(point) for point in record.trigger_points],
            circuit_breakers=[dict(item) for item in record.circuit_breakers],
            missing_provider_facts=list(record.missing_provider_facts),
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_execution_program_event(
        record: ExecutionProgramEventRecord,
    ) -> ExecutionProgramEventRecord:
        return ExecutionProgramEventRecord(
            event_id=record.event_id,
            program_id=record.program_id,
            event_type=record.event_type,
            summary=record.summary,
            payload=dict(record.payload),
            created_at=record.created_at,
        )

    @classmethod
    def _seed_provider_configs(cls, session: Session) -> None:
        changed = False
        for descriptor in PROVIDERS:
            record = session.get(ProviderConfigRecord, descriptor.id)
            if record is None:
                new_record = cls._provider_config_from_descriptor(descriptor)
                if session.get_bind().dialect.name == "sqlite":
                    session.execute(sqlite_insert(ProviderConfigRecord).values(**new_record.model_dump()).on_conflict_do_nothing(index_elements=["provider_id"]))
                else:
                    session.add(new_record)
                changed = True
                continue

            record.name = descriptor.name
            record.role = descriptor.role
            record.capabilities = list(descriptor.capabilities)
            record.primary_use = descriptor.primary_use
            record.control_surface = descriptor.control_surface
            record.write_authority = descriptor.write_authority
            default_config = default_provider_config(descriptor.id)
            current_config = dict(record.config)
            if (
                (
                    default_config.get("config_version") is not None
                    and current_config.get("config_version") != default_config["config_version"]
                )
                or (
                    descriptor.id == "openai-codex-oauth-llm"
                    and (
                        current_config.get("provider") != default_config.get("provider")
                        or "oauth_authorization_url" in current_config
                        or "oauth_token_url" in current_config
                    )
                )
            ):
                record.config = dict(default_config)
            else:
                record.config = {
                    **default_config,
                    **current_config,
                }
            if descriptor.status == "disabled":
                record.status = "disabled"
                record.enabled = False
            elif descriptor.status == "available" and record.status in {"planned", "needs_key"}:
                record.status = descriptor.status
            elif record.status == "disabled":
                record.status = descriptor.status
            changed = True
        if changed:
            session.commit()

    @classmethod
    def _seed_provider_role_assignments(cls, session: Session) -> None:
        changed = False
        research = session.get(ProviderRoleAssignmentRecord, "research_llm")
        for assignment in DEFAULT_PROVIDER_ROLE_ASSIGNMENTS:
            if session.get(ProviderRoleAssignmentRecord, assignment.role_key) is not None:
                continue
            new_record = ProviderRoleAssignmentRecord(
                    role_key=assignment.role_key,
                    provider_id=research.provider_id if research and assignment.role_key in {"research_designer", "research_extractor"} else assignment.provider_id,
                    surface=assignment.surface,
                )
            if session.get_bind().dialect.name == "sqlite":
                session.execute(sqlite_insert(ProviderRoleAssignmentRecord).values(**new_record.model_dump()).on_conflict_do_nothing(index_elements=["role_key"]))
            else:
                session.add(new_record)
            changed = True
        if changed:
            session.commit()

    @staticmethod
    def _provider_config_from_descriptor(descriptor: Any) -> ProviderConfigRecord:
        return ProviderConfigRecord(
            provider_id=descriptor.id,
            name=descriptor.name,
            role=descriptor.role,
            status=descriptor.status,
            capabilities=list(descriptor.capabilities),
            primary_use=descriptor.primary_use,
            control_surface=descriptor.control_surface,
            write_authority=descriptor.write_authority,
            enabled=descriptor.status == "available",
            config=default_provider_config(descriptor.id),
            health={"status": "not_checked"},
        )

    @staticmethod
    def _sanitize_config(value: dict[str, Any]) -> dict[str, Any]:
        blocked = {"secret", "secret_value", "raw_secret", "api_key", "access_token", "refresh_token", "password"}
        return {key: item for key, item in value.items() if key.lower() not in blocked}

    @staticmethod
    def _sanitize_health(value: dict[str, Any]) -> dict[str, Any]:
        sanitized = UiRepository._sanitize_config(value)
        secret_health = value.get("secret")
        if isinstance(secret_health, dict):
            sanitized["secret"] = UiRepository._sanitize_config(secret_health)
        return sanitized

    @staticmethod
    def _detach_private_office_event(record: PrivateOfficeEventRecord) -> PrivateOfficeEventRecord:
        return PrivateOfficeEventRecord(
            event_id=record.event_id,
            event_type=record.event_type,
            summary=record.summary,
            actor=record.actor,
            entity_id=record.entity_id,
            payload=dict(record.payload),
            created_at=record.created_at,
        )

    @staticmethod
    def _detach_observability_trace(
        record: ObservabilityTraceRecord,
    ) -> ObservabilityTraceRecord:
        return ObservabilityTraceRecord(
            trace_id=record.trace_id,
            run_id=record.run_id,
            provider=record.provider,
            status=record.status,
            external_trace_id=record.external_trace_id,
            metadata_payload=dict(record.metadata_payload),
            cost=dict(record.cost),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_private_office_entity(record: PrivateOfficeEntityRecord) -> PrivateOfficeEntityRecord:
        return PrivateOfficeEntityRecord(
            entity_id=record.entity_id,
            entity_type=record.entity_type,
            label=record.label,
            external_id=record.external_id,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_private_office_edge(record: PrivateOfficeEdgeRecord) -> PrivateOfficeEdgeRecord:
        return PrivateOfficeEdgeRecord(
            edge_id=record.edge_id,
            source_entity_id=record.source_entity_id,
            target_entity_id=record.target_entity_id,
            relationship=record.relationship,
            payload=dict(record.payload),
            created_at=record.created_at,
        )

    @staticmethod
    def _require_private_office_entity(
        session: Session,
        entity_id: str,
    ) -> PrivateOfficeEntityRecord:
        record = session.get(PrivateOfficeEntityRecord, entity_id)
        if record is None:
            raise KeyError(entity_id)
        return record

    @staticmethod
    def _normalize_required_symbol(symbol: str, label: str) -> str:
        normalized = symbol.strip().upper()
        if not normalized:
            raise ValueError(f"{label} is required")
        return normalized

    @staticmethod
    def _validate_portfolio_mandate(
        *,
        control_mode: str,
        funding_limit: float,
        max_position_percent: float,
        max_drawdown_percent: float,
        daily_turnover_limit_percent: float,
        paper_mode_required: bool,
        kill_switch_enabled: bool,
    ) -> None:
        for label, value in {
            "funding_limit": funding_limit,
            "max_position_percent": max_position_percent,
            "max_drawdown_percent": max_drawdown_percent,
            "daily_turnover_limit_percent": daily_turnover_limit_percent,
        }.items():
            if value <= 0:
                raise ValueError(f"{label} must be greater than zero")
        if control_mode == "ai-managed-high-risk" and not paper_mode_required:
            raise ValueError("ai-managed-high-risk mandates require paper mode proving")
        if control_mode == "ai-managed-high-risk" and not kill_switch_enabled:
            raise ValueError("ai-managed-high-risk mandates require a kill switch")

    @staticmethod
    def _validate_agent_workflow(
        *,
        name: str,
        agent_class: str,
        graph_runtime: str,
        nodes: list[dict[str, Any]],
        required_provider_roles: dict[str, str],
    ) -> None:
        if not name.strip():
            raise ValueError("workflow name is required")
        if agent_class not in {"research", "execution"}:
            raise ValueError("agent_class must be research or execution")
        if graph_runtime not in {"langgraph", "langchain", "manual"}:
            raise ValueError("graph_runtime must be langgraph, langchain, or manual")
        if not nodes:
            raise ValueError("workflow requires at least one node")
        if agent_class == "execution" and "safety" not in required_provider_roles:
            raise ValueError("execution workflows require a safety provider role")

    @classmethod
    def _validate_agent_operation(
        cls,
        *,
        agent_id: str,
        agent_name: str,
        room_id: str,
        operation_type: str,
        status: str,
        authority: str,
    ) -> None:
        if not agent_id.strip():
            raise ValueError("agent operation agent_id is required")
        if not agent_name.strip():
            raise ValueError("agent operation agent_name is required")
        if not room_id.strip():
            raise ValueError("agent operation room_id is required")
        if operation_type not in cls._AGENT_OPERATION_TYPES:
            raise ValueError(
                "agent operation type must be research_report, portfolio_review, "
                "execution_preview, trigger_evaluation, or builder_workflow"
            )
        if status not in cls._AGENT_OPERATION_STATUSES:
            raise ValueError("agent operation status must be queued, running, completed, or failed")
        if authority not in cls._AGENT_OPERATION_AUTHORITIES:
            raise ValueError(
                "agent operation authority must be research_only, paper_only, or approval_required"
            )
        if (
            operation_type in cls._EXECUTION_OPERATION_TYPES
            and authority not in {"paper_only", "approval_required"}
        ):
            raise ValueError("execution operations must be paper_only or approval_required")

    @staticmethod
    def _detach_portfolio_mandate(record: PortfolioMandateRecord) -> PortfolioMandateRecord:
        return PortfolioMandateRecord(
            mandate_id=record.mandate_id,
            name=record.name,
            control_mode=record.control_mode,
            account_ref=record.account_ref,
            status=record.status,
            funding_limit=record.funding_limit,
            max_position_percent=record.max_position_percent,
            max_drawdown_percent=record.max_drawdown_percent,
            daily_turnover_limit_percent=record.daily_turnover_limit_percent,
            paper_mode_required=record.paper_mode_required,
            kill_switch_enabled=record.kill_switch_enabled,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_provider_role_assignment(
        record: ProviderRoleAssignmentRecord,
    ) -> ProviderRoleAssignmentRecord:
        return ProviderRoleAssignmentRecord(
            role_key=record.role_key,
            provider_id=record.provider_id,
            surface=record.surface,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_agent_workflow(record: AgentWorkflowRecord) -> AgentWorkflowRecord:
        return AgentWorkflowRecord(
            workflow_id=record.workflow_id,
            name=record.name,
            agent_class=record.agent_class,
            graph_runtime=record.graph_runtime,
            status=record.status,
            nodes=[dict(node) for node in record.nodes],
            edges=[dict(edge) for edge in record.edges],
            required_provider_roles=dict(record.required_provider_roles),
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_agent_operation(record: AgentOperationRecord) -> AgentOperationRecord:
        return AgentOperationRecord(
            operation_id=record.operation_id,
            agent_id=record.agent_id,
            agent_name=record.agent_name,
            room_id=record.room_id,
            symbol=record.symbol,
            operation_type=record.operation_type,
            status=record.status,
            authority=record.authority,
            source_workflow_id=record.source_workflow_id,
            linked_run_id=record.linked_run_id,
            linked_execution_program_id=record.linked_execution_program_id,
            payload=dict(record.payload),
            started_at=record.started_at,
            completed_at=record.completed_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_agent_pack(record: AgentPackRecord) -> AgentPackRecord:
        return AgentPackRecord(
            pack_id=record.pack_id,
            source_url=record.source_url,
            source_commit=record.source_commit,
            license=record.license,
            status=record.status,
            manifest=dict(record.manifest),
            imported_at=record.imported_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_imported_agent(record: ImportedAgentRecord) -> ImportedAgentRecord:
        return ImportedAgentRecord(
            agent_id=record.agent_id,
            pack_id=record.pack_id,
            source_slug=record.source_slug,
            name=record.name,
            description=record.description,
            agent_class=record.agent_class,
            system_prompt=record.system_prompt,
            guardrails=list(record.guardrails),
            skills=list(record.skills),
            commands=list(record.commands),
            required_provider_roles=dict(record.required_provider_roles),
            required_connectors=list(record.required_connectors),
            tool_policy=dict(record.tool_policy),
            output_schema=dict(record.output_schema),
            security_profile=dict(record.security_profile),
            status=record.status,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_imported_skill(record: ImportedSkillRecord) -> ImportedSkillRecord:
        return ImportedSkillRecord(
            skill_id=record.skill_id,
            pack_id=record.pack_id,
            source_path=record.source_path,
            name=record.name,
            description=record.description,
            instructions_markdown=record.instructions_markdown,
            references=list(record.references),
            scripts=list(record.scripts),
            artifact_requirements=dict(record.artifact_requirements),
            status=record.status,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_mcp_connector(record: McpConnectorRecord) -> McpConnectorRecord:
        return McpConnectorRecord(
            connector_id=record.connector_id,
            name=record.name,
            url=record.url,
            provider_id=record.provider_id,
            required_secret_ref=record.required_secret_ref,
            capabilities=list(record.capabilities),
            health=dict(record.health),
            enabled=record.enabled,
            subscription_required=record.subscription_required,
            payload=dict(record.payload),
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_snapshot_manifest(record: SnapshotManifestRecord) -> SnapshotManifestRecord:
        return SnapshotManifestRecord(
            snapshot_id=record.snapshot_id,
            storage_profile=record.storage_profile,
            encryption_mode=record.encryption_mode,
            offsite_target=record.offsite_target,
            manifest=dict(record.manifest),
            created_at=record.created_at,
        )

    @staticmethod
    def _detach_market_data_snapshot(record: MarketDataSnapshotRecord) -> MarketDataSnapshotRecord:
        return MarketDataSnapshotRecord(
            snapshot_id=record.snapshot_id,
            provider_id=record.provider_id,
            symbol=record.symbol,
            snapshot_kind=record.snapshot_kind,
            feed=record.feed,
            timeframe=record.timeframe,
            payload=dict(record.payload),
            created_at=record.created_at,
        )

    @staticmethod
    def _require_run(session: Session, run_id: str) -> RunRecord:
        record = session.get(RunRecord, run_id)
        if record is None:
            raise KeyError(run_id)
        return record

    @staticmethod
    def _require_observability_trace(
        session: Session,
        run_id: str,
    ) -> ObservabilityTraceRecord:
        statement = select(ObservabilityTraceRecord).where(
            ObservabilityTraceRecord.run_id == run_id
        )
        record = session.exec(statement).first()
        if record is None:
            raise KeyError(run_id)
        return record

    @staticmethod
    def _require_trade_intent(
        session: Session, intent_id: str
    ) -> TradeIntentRecord:
        record = session.get(TradeIntentRecord, intent_id)
        if record is None:
            raise KeyError(intent_id)
        return record

    @staticmethod
    def _require_execution_program(
        session: Session,
        program_id: str,
    ) -> ExecutionProgramRecord:
        record = session.get(ExecutionProgramRecord, program_id)
        if record is None:
            raise KeyError(program_id)
        return record

    # ------------------------------------------------------------------
    # Watcher primitive
    # ------------------------------------------------------------------

    _WATCHER_CONDITION_TYPES = {
        "price_above",
        "price_below",
        "change_pct_above",
        "change_pct_below",
        "volume_above",
    }

    # ------------------------------------------------------------------
    # Quick scan (cheap wide-pass opportunity funnel)
    # ------------------------------------------------------------------

    def insert_quick_scan(
        self,
        *,
        symbol: str,
        stance: str,
        conviction: int,
        thesis: str,
        catalyst: str,
        risk: str,
        model: str,
    ) -> QuickScanRecord:
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("quick scan symbol is required")
        if stance not in {"buy", "hold", "avoid"}:
            raise ValueError(f"unsupported quick scan stance: {stance}")
        record = QuickScanRecord(
            symbol=normalized_symbol,
            stance=stance,
            conviction=max(0, min(100, int(conviction))),
            thesis=thesis,
            catalyst=catalyst,
            risk=risk,
            model=model,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_quick_scan(record)

    def latest_quick_scans(
        self,
        symbols: list[str] | None = None,
        limit: int = 50,
    ) -> list[QuickScanRecord]:
        """Return the most recent quick-scan row per symbol.

        When ``symbols`` is provided only those tickers are considered (result
        preserves requested order); otherwise every scanned symbol is returned,
        capped at ``limit``. Symbols are normalized to upper case.
        """

        requested = (
            [symbol.strip().upper() for symbol in symbols if symbol.strip()]
            if symbols is not None
            else None
        )
        statement = select(QuickScanRecord).order_by(QuickScanRecord.created_at.desc())
        if requested:
            statement = statement.where(QuickScanRecord.symbol.in_(requested))
        with self._session_factory() as session:
            records = session.exec(statement).all()
            latest_by_symbol: dict[str, QuickScanRecord] = {}
            for record in records:
                if record.symbol not in latest_by_symbol:
                    latest_by_symbol[record.symbol] = record
                if requested is None and len(latest_by_symbol) >= limit:
                    break
            ordered = (
                [latest_by_symbol[symbol] for symbol in requested if symbol in latest_by_symbol]
                if requested
                else list(latest_by_symbol.values())
            )
            return [self._detach_quick_scan(record) for record in ordered]

    @staticmethod
    def _detach_quick_scan(record: QuickScanRecord) -> QuickScanRecord:
        return QuickScanRecord(
            scan_row_id=record.scan_row_id,
            symbol=record.symbol,
            stance=record.stance,
            conviction=record.conviction,
            thesis=record.thesis,
            catalyst=record.catalyst,
            risk=record.risk,
            model=record.model,
            created_at=record.created_at,
        )

    def create_watcher(
        self,
        *,
        name: str,
        symbol: str,
        condition_type: str,
        threshold: float,
        enabled: bool = True,
        cooldown_seconds: int = 300,
        payload: dict[str, Any] | None = None,
        linked_position_id: str | None = None,
        linked_run_id: str | None = None,
    ) -> WatcherRecord:
        if not name.strip():
            raise ValueError("watcher name is required")
        normalized_symbol = symbol.strip().upper()
        if not normalized_symbol:
            raise ValueError("watcher symbol is required")
        if condition_type not in self._WATCHER_CONDITION_TYPES:
            raise ValueError(f"unsupported watcher condition: {condition_type}")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        merged_payload: dict[str, Any] = dict(payload or {})
        merged_payload["cooldown_seconds"] = int(cooldown_seconds)
        record = WatcherRecord(
            name=name.strip(),
            symbol=normalized_symbol,
            condition_type=condition_type,
            threshold=float(threshold),
            enabled=enabled,
            payload=merged_payload,
            linked_position_id=linked_position_id,
            linked_run_id=linked_run_id,
        )
        with self._session_factory() as session:
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_watcher(record)

    def list_watchers(
        self,
        *,
        symbol: str | None = None,
        enabled: bool | None = True,
        limit: int = 100,
    ) -> list[WatcherRecord]:
        statement = select(WatcherRecord).order_by(WatcherRecord.created_at.desc())
        if symbol is not None:
            statement = statement.where(WatcherRecord.symbol == symbol.strip().upper())
        if enabled is not None:
            statement = statement.where(WatcherRecord.enabled == enabled)
        if limit:
            statement = statement.limit(int(limit))
        with self._session_factory() as session:
            return [self._detach_watcher(rec) for rec in session.exec(statement).all()]

    def get_watcher(self, watcher_id: str) -> WatcherRecord:
        with self._session_factory() as session:
            record = session.get(WatcherRecord, watcher_id)
            if record is None:
                raise KeyError(watcher_id)
            return self._detach_watcher(record)

    def update_watcher(
        self,
        watcher_id: str,
        *,
        name: str | None = None,
        threshold: float | None = None,
        enabled: bool | None = None,
        cooldown_seconds: int | None = None,
    ) -> WatcherRecord:
        with self._session_factory() as session:
            record = session.get(WatcherRecord, watcher_id)
            if record is None:
                raise KeyError(watcher_id)
            if name is not None:
                normalized = name.strip()
                if not normalized:
                    raise ValueError("watcher name cannot be empty")
                record.name = normalized
            if threshold is not None:
                record.threshold = float(threshold)
            if enabled is not None:
                record.enabled = bool(enabled)
            if cooldown_seconds is not None:
                if cooldown_seconds < 0:
                    raise ValueError("cooldown_seconds must be >= 0")
                payload = dict(record.payload or {})
                payload["cooldown_seconds"] = int(cooldown_seconds)
                record.payload = payload
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return self._detach_watcher(record)

    def delete_watcher(self, watcher_id: str) -> None:
        with self._session_factory() as session:
            record = session.get(WatcherRecord, watcher_id)
            if record is None:
                raise KeyError(watcher_id)
            session.delete(record)
            session.commit()

    def record_watcher_fire(
        self,
        *,
        watcher_id: str,
        symbol: str,
        condition_type: str,
        threshold: float,
        observed_value: float,
        payload: dict[str, Any] | None = None,
    ) -> WatcherFireRecord:
        fired_at = now_utc()
        fire = WatcherFireRecord(
            watcher_id=watcher_id,
            symbol=symbol.strip().upper(),
            condition_type=condition_type,
            threshold=float(threshold),
            observed_value=float(observed_value),
            payload=dict(payload or {}),
            fired_at=fired_at,
        )
        with self._session_factory() as session:
            watcher = session.get(WatcherRecord, watcher_id)
            if watcher is None:
                raise KeyError(watcher_id)
            watcher.last_fired_at = fired_at
            watcher.fire_count = (watcher.fire_count or 0) + 1
            watcher.updated_at = fired_at
            session.add(watcher)
            session.add(fire)
            session.commit()
            session.refresh(fire)
            return self._detach_watcher_fire(fire)

    def list_watcher_fires(
        self,
        *,
        watcher_id: str | None = None,
        symbol: str | None = None,
        since: Any | None = None,
        limit: int = 50,
    ) -> list[WatcherFireRecord]:
        statement = select(WatcherFireRecord).order_by(WatcherFireRecord.fired_at.desc())
        if watcher_id is not None:
            statement = statement.where(WatcherFireRecord.watcher_id == watcher_id)
        if symbol is not None:
            statement = statement.where(WatcherFireRecord.symbol == symbol.strip().upper())
        if since is not None:
            statement = statement.where(WatcherFireRecord.fired_at >= since)
        if limit:
            statement = statement.limit(int(limit))
        with self._session_factory() as session:
            return [self._detach_watcher_fire(rec) for rec in session.exec(statement).all()]

    @staticmethod
    def _detach_watcher(record: WatcherRecord) -> WatcherRecord:
        return WatcherRecord(
            watcher_id=record.watcher_id,
            name=record.name,
            symbol=record.symbol,
            condition_type=record.condition_type,
            threshold=record.threshold,
            enabled=record.enabled,
            payload=dict(record.payload or {}),
            linked_position_id=record.linked_position_id,
            linked_run_id=record.linked_run_id,
            last_fired_at=record.last_fired_at,
            fire_count=record.fire_count,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    @staticmethod
    def _detach_watcher_fire(record: WatcherFireRecord) -> WatcherFireRecord:
        return WatcherFireRecord(
            fire_id=record.fire_id,
            watcher_id=record.watcher_id,
            symbol=record.symbol,
            fired_at=record.fired_at,
            observed_value=record.observed_value,
            threshold=record.threshold,
            condition_type=record.condition_type,
            payload=dict(record.payload or {}),
        )
