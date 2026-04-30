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
    SQLModel.metadata.create_all(engine)


def session_generator(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    with session_factory() as session:
        yield session
