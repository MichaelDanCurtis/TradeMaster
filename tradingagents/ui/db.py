from __future__ import annotations

from collections.abc import Iterator
from importlib import import_module

from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine


def create_session_factory(database_url: str) -> tuple[Engine, sessionmaker[Session]]:
    engine = create_engine(database_url)
    session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        expire_on_commit=False,
    )
    return engine, session_factory


def init_db(engine: Engine) -> None:
    import_module("tradingagents.ui.models")
    import_module("tradingagents.ui.explorer_briefs")
    import_module("tradingagents.ui.evidence_attachments")
    import_module("tradingagents.ui.research_desk")
    import_module("tradingagents.ui.forecast_lab")
    import_module("tradingagents.research.models")
    import_module("tradingagents.research.execution_models")
    import_module("tradingagents.research.accounting_models")
    import_module("tradingagents.research.deployment_models")
    import_module("tradingagents.scheduling.models")
    SQLModel.metadata.create_all(engine)
    from tradingagents.research.repository import install_immutability_guards

    install_immutability_guards(engine)
    from tradingagents.research.execution_repository import install_execution_guards
    install_execution_guards(engine)
    from tradingagents.research.accounting_repository import install_accounting_guards
    install_accounting_guards(engine)
    from tradingagents.research.deployment_repository import install_deployment_guards
    install_deployment_guards(engine)
    from tradingagents.research.deployment_jobs import install_job_guards
    install_job_guards(engine)
    from tradingagents.scheduling.repository import install_schedule_guards
    install_schedule_guards(engine)


def session_generator(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
