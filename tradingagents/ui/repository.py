from __future__ import annotations

from typing import Any

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from tradingagents.ui.events import RunConfig, RunEvent, RunStatus, RunSummary
from tradingagents.ui.models import (
    ApprovalRecord,
    BrokerOrderRecord,
    DecisionRecord,
    ObservabilityTraceRecord,
    PrivateOfficeEdgeRecord,
    PrivateOfficeEntityRecord,
    PrivateOfficeEventRecord,
    PortfolioMandateRecord,
    ProviderConfigRecord,
    RunEventRecord,
    RunRecord,
    SnapshotManifestRecord,
    TradeIntentRecord,
    now_utc,
)
from tradingagents.ui.providers import PROVIDERS, provider_descriptor_by_id


class UiRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

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
            return [self._run_summary(record) for record in records]

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

    def create_trade_intent(
        self,
        run_id: str,
        symbol: str,
        side: str,
        notional: float,
        order_type: str = "market",
    ) -> TradeIntentRecord:
        with self._session_factory() as session:
            self._require_run(session, run_id)
            record = TradeIntentRecord(
                run_id=run_id,
                symbol=symbol,
                side=side,
                notional=notional,
                order_type=order_type,
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

    def upsert_provider_config(
        self,
        provider_id: str,
        *,
        enabled: bool | None = None,
        secret_ref: str | None = None,
        config: dict[str, Any] | None = None,
        health: dict[str, Any] | None = None,
        status: str | None = None,
    ) -> ProviderConfigRecord:
        with self._session_factory() as session:
            self._seed_provider_configs(session)
            record = session.get(ProviderConfigRecord, provider_id)
            descriptor = provider_descriptor_by_id(provider_id)
            if record is None and descriptor is None:
                raise KeyError(provider_id)
            if record is None and descriptor is not None:
                record = self._provider_config_from_descriptor(descriptor)
            if enabled is not None:
                record.enabled = enabled
            if secret_ref is not None:
                record.secret_ref = secret_ref
            if config is not None:
                record.config = self._sanitize_config(config)
            if health is not None:
                record.health = self._sanitize_health(health)
            if status is not None:
                record.status = status
            record.updated_at = now_utc()
            session.add(record)
            session.commit()
            session.refresh(record)
            return record

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

    @classmethod
    def _seed_provider_configs(cls, session: Session) -> None:
        changed = False
        for descriptor in PROVIDERS:
            if session.get(ProviderConfigRecord, descriptor.id) is None:
                session.add(cls._provider_config_from_descriptor(descriptor))
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
            config={},
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
