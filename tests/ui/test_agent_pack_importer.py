from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from tradingagents.ui.agent_packs.importer import import_agent_pack
from tradingagents.ui.api import create_app
from tradingagents.ui.db import create_session_factory, init_db
from tradingagents.ui.repository import UiRepository


def test_importer_normalizes_anthropic_style_agent_pack(tmp_path: Path):
    pack_root = _write_mini_financial_services_pack(tmp_path / "financial-services")
    engine, session_factory = create_session_factory(f"sqlite:///{tmp_path / 'ui.db'}")
    init_db(engine)
    repo = UiRepository(session_factory)

    result = import_agent_pack(
        pack_root,
        repo,
        pack_id="anthropic-financial-services",
        source_url="https://github.com/anthropics/financial-services",
        source_commit="test-fixture",
    )

    agents = repo.list_imported_agents(pack_id="anthropic-financial-services")
    skills = repo.list_imported_skills(pack_id="anthropic-financial-services")
    connectors = repo.list_mcp_connectors()

    assert result.agent_count == 1
    assert result.skill_count == 1
    assert result.connector_count == 1
    assert agents[0].agent_id == "anthropic-financial-services:market-researcher"
    assert agents[0].source_slug == "market-researcher"
    assert agents[0].agent_class == "research"
    assert agents[0].required_connectors == ["factset"]
    assert agents[0].tool_policy["call_mcp"] is True
    assert agents[0].payload["managed_model"] == "claude-opus-4-7"
    assert skills[0].skill_id == "anthropic-financial-services:sector-overview"
    assert connectors[0].connector_id == "factset"
    assert connectors[0].url == "https://mcp.factset.com/mcp"


def test_agent_pack_api_imports_and_lists_normalized_records(tmp_path: Path):
    pack_root = _write_mini_financial_services_pack(tmp_path / "financial-services")
    client = TestClient(create_app(f"sqlite:///{tmp_path / 'api.db'}"))

    imported = client.post(
        "/api/agent-packs/import",
        json={
            "pack_id": "anthropic-financial-services",
            "source_path": str(pack_root),
            "source_url": "https://github.com/anthropics/financial-services",
            "source_commit": "test-fixture",
        },
    )
    packs = client.get("/api/agent-packs")
    agents = client.get("/api/imported-agents")
    skills = client.get("/api/imported-skills")
    connectors = client.get("/api/mcp-connectors")

    assert imported.status_code == 200
    assert imported.json()["agent_count"] == 1
    assert packs.json()["packs"][0]["pack_id"] == "anthropic-financial-services"
    assert agents.json()["agents"][0]["name"] == "Market Researcher"
    assert skills.json()["skills"][0]["name"] == "sector-overview"
    assert connectors.json()["connectors"][0]["connector_id"] == "factset"


def _write_mini_financial_services_pack(root: Path) -> Path:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "marketplace.json").write_text(
        json.dumps(
            {
                "name": "claude-for-financial-services",
                "plugins": [
                    {
                        "name": "market-researcher",
                        "source": "./plugins/agent-plugins/market-researcher",
                        "description": "Sector research agent",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    agent_dir = root / "plugins" / "agent-plugins" / "market-researcher"
    (agent_dir / ".claude-plugin").mkdir(parents=True)
    (agent_dir / "agents").mkdir()
    (agent_dir / "skills" / "sector-overview").mkdir(parents=True)
    (agent_dir / ".claude-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "market-researcher",
                "version": "0.1.0",
                "description": "Sector or theme to industry overview.",
            }
        ),
        encoding="utf-8",
    )
    (agent_dir / "agents" / "market-researcher.md").write_text(
        """---
name: market-researcher
description: Produces sector or thematic market research.
tools: Read, Write, Edit, mcp__factset__*
---

You are the Market Researcher.

## Workflow

1. Scope the ask.
2. Pull FactSet data.

## Guardrails

- Cite every number.
- No distribution.
""",
        encoding="utf-8",
    )
    (agent_dir / "skills" / "sector-overview" / "SKILL.md").write_text(
        """---
name: sector-overview
description: Draft a sector overview.
---

Build market size, growth, structure, drivers, and why-now narrative.
""",
        encoding="utf-8",
    )

    vertical_dir = root / "plugins" / "vertical-plugins" / "financial-analysis"
    vertical_dir.mkdir(parents=True)
    (vertical_dir / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "factset": {
                        "type": "http",
                        "url": "https://mcp.factset.com/mcp",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    cookbook = root / "managed-agent-cookbooks" / "market-researcher"
    cookbook.mkdir(parents=True)
    (cookbook / "agent.yaml").write_text(
        """name: market-researcher
model: claude-opus-4-7
tools:
  - type: agent_toolset_20260401
    default_config: { enabled: false }
    configs:
      - { name: read, enabled: true }
      - { name: grep, enabled: true }
  - { type: mcp_toolset, mcp_server_name: factset, default_config: { enabled: true } }
mcp_servers:
  - { type: url, name: factset, url: "${FACTSET_MCP_URL}" }
callable_agents:
  - { manifest: ./subagents/sector-reader.yaml }
""",
        encoding="utf-8",
    )
    (cookbook / "steering-examples.json").write_text(
        json.dumps([{"event": "Primer: US data-center power"}]),
        encoding="utf-8",
    )
    return root
