from __future__ import annotations

from typing import Any

from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, select

from tradingagents.ui.events import RunConfig, RunEvent, RunStatus, RunSummary
from tradingagents.ui.models import (
    ApprovalRecord,
    BrokerOrderRecord,
    DecisionRecord,
    RunEventRecord,
    RunRecord,
    TradeIntentRecord,
    now_utc,
)


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
    def _require_run(session: Session, run_id: str) -> RunRecord:
        record = session.get(RunRecord, run_id)
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
