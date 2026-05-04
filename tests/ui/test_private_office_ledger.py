from pathlib import Path

from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository


def _repo(tmp_path: Path) -> UiRepository:
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    return UiRepository(session_factory)


def test_private_office_events_append_and_filter_by_entity(tmp_path: Path):
    repo = _repo(tmp_path)

    first = repo.append_private_office_event(
        event_type="agent.message.created",
        summary="Goals team updated the yacht dossier.",
        actor="Goal Steward",
        entity_id="goal_yacht",
        payload={"surface": "goal-dossier"},
    )
    second = repo.append_private_office_event(
        event_type="provider.health.checked",
        summary="Alpaca market data still needs credentials.",
        actor="Provider Registry",
        entity_id="provider_alpaca_market_data",
        payload={"status": "needs_key"},
    )

    all_events = repo.list_private_office_events()
    goal_events = repo.list_private_office_events(entity_id="goal_yacht")

    assert [event.event_id for event in all_events] == [first.event_id, second.event_id]
    assert [event.event_id for event in goal_events] == [first.event_id]
    assert goal_events[0].payload == {"surface": "goal-dossier"}


def test_private_office_entities_and_edges_model_goal_dependencies(tmp_path: Path):
    repo = _repo(tmp_path)

    goal = repo.upsert_private_office_entity(
        entity_id="goal_yacht",
        entity_type="goal",
        label="Acquire a 68-foot yacht",
        payload={"status": "planning"},
    )
    asset = repo.upsert_private_office_entity(
        entity_id="asset_navetta_68",
        entity_type="asset",
        label="Absolute / Navetta 68 class yacht",
    )
    tax = repo.upsert_private_office_entity(
        entity_id="team_tax_structure",
        entity_type="agent-team",
        label="Tax & Structure Body",
    )
    asset_edge = repo.link_private_office_entities(
        source_entity_id=goal.entity_id,
        target_entity_id=asset.entity_id,
        relationship="targets",
    )
    tax_edge = repo.link_private_office_entities(
        source_entity_id=goal.entity_id,
        target_entity_id=tax.entity_id,
        relationship="blocked_by",
        payload={"severity": "urgent"},
    )

    edges = repo.list_private_office_edges(source_entity_id="goal_yacht")
    reread_goal = repo.get_private_office_entity("goal_yacht")

    assert reread_goal.payload == {"status": "planning"}
    assert [edge.edge_id for edge in edges] == [asset_edge.edge_id, tax_edge.edge_id]
    assert {edge.relationship for edge in edges} == {"targets", "blocked_by"}
    assert edges[1].payload == {"severity": "urgent"}


def test_private_office_entity_updates_are_defensive(tmp_path: Path):
    repo = _repo(tmp_path)
    entity = repo.upsert_private_office_entity(
        entity_id="provider_alpaca_market_data",
        entity_type="provider",
        label="Alpaca Market Data",
        payload={"capabilities": ["historical-bars"]},
    )

    entity.payload["capabilities"].append("mutated")
    fresh = repo.get_private_office_entity("provider_alpaca_market_data")

    assert fresh.payload == {"capabilities": ["historical-bars"]}
