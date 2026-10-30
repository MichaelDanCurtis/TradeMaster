from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from tradingagents.ui.models import AgentPackRecord
from tradingagents.ui.repository import UiRepository


@dataclass(frozen=True)
class AgentPackImportResult:
    pack: AgentPackRecord
    agent_count: int
    skill_count: int
    connector_count: int


def import_agent_pack(
    source_path: str | Path,
    repository: UiRepository,
    *,
    pack_id: str,
    source_url: str | None = None,
    source_commit: str | None = None,
) -> AgentPackImportResult:
    root = Path(source_path).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError("agent pack source_path must be an existing directory")

    marketplace = _read_json(root / ".claude-plugin" / "marketplace.json", default={})
    license_text = _read_optional_text(root / "LICENSE")
    pack = repository.upsert_agent_pack(
        pack_id=pack_id,
        source_url=source_url,
        source_commit=source_commit,
        license=license_text.splitlines()[0] if license_text else None,
        manifest=marketplace,
        status="imported",
    )

    connectors = _import_mcp_connectors(root, repository)
    cookbooks = _read_cookbooks(root)
    skills = _import_skills(root, repository, pack_id=pack_id)
    agents = _import_agents(
        root,
        repository,
        pack_id=pack_id,
        cookbooks=cookbooks,
        skills_by_plugin=skills,
    )

    return AgentPackImportResult(
        pack=pack,
        agent_count=agents,
        skill_count=sum(len(items) for items in skills.values()),
        connector_count=connectors,
    )


def _import_mcp_connectors(root: Path, repository: UiRepository) -> int:
    connector_ids: set[str] = set()
    for mcp_file in sorted(root.glob("plugins/**/.mcp.json")):
        payload = _read_json(mcp_file, default={})
        servers = payload.get("mcpServers")
        if not isinstance(servers, dict):
            continue
        for connector_id, config in servers.items():
            if not isinstance(config, dict):
                continue
            url = config.get("url")
            if not isinstance(url, str) or not url:
                continue
            repository.upsert_mcp_connector(
                connector_id=connector_id,
                name=_humanize(connector_id),
                url=url,
                provider_id=connector_id,
                capabilities=["mcp", "read-only-financial-data"],
                health={"status": "not_checked"},
                enabled=False,
                subscription_required=True,
                payload={
                    "source_path": str(mcp_file.relative_to(root)),
                    "type": config.get("type", "http"),
                },
            )
            connector_ids.add(connector_id)
    return len(connector_ids)


def _read_cookbooks(root: Path) -> dict[str, dict[str, Any]]:
    cookbooks: dict[str, dict[str, Any]] = {}
    for cookbook_file in sorted(root.glob("managed-agent-cookbooks/*/agent.yaml")):
        payload = yaml.safe_load(cookbook_file.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            continue
        slug = str(payload.get("name") or cookbook_file.parent.name)
        steering = _read_json(cookbook_file.parent / "steering-examples.json", default=[])
        payload["source_path"] = str(cookbook_file.relative_to(root))
        payload["steering_examples"] = steering
        cookbooks[slug] = payload
    return cookbooks


def _import_skills(
    root: Path,
    repository: UiRepository,
    *,
    pack_id: str,
) -> dict[str, list[str]]:
    skills_by_plugin: dict[str, list[str]] = {}
    for skill_file in sorted(root.glob("plugins/**/skills/*/SKILL.md")):
        metadata, body = _split_frontmatter(skill_file.read_text(encoding="utf-8"))
        slug = skill_file.parent.name
        plugin_slug = _plugin_slug_for(skill_file)
        skill_id = f"{pack_id}:{slug}"
        repository.upsert_imported_skill(
            skill_id=skill_id,
            pack_id=pack_id,
            source_path=str(skill_file.relative_to(root)),
            name=str(metadata.get("name") or slug),
            description=str(metadata.get("description") or ""),
            instructions_markdown=body.strip(),
            references=[
                str(path.relative_to(root))
                for path in sorted(skill_file.parent.glob("references/**/*"))
                if path.is_file()
            ],
            scripts=[
                str(path.relative_to(root))
                for path in sorted(skill_file.parent.glob("scripts/**/*"))
                if path.is_file()
            ],
            artifact_requirements={},
            status="imported",
            payload={"source_plugin": plugin_slug},
        )
        skills_by_plugin.setdefault(plugin_slug, []).append(slug)
    return skills_by_plugin


def _import_agents(
    root: Path,
    repository: UiRepository,
    *,
    pack_id: str,
    cookbooks: dict[str, dict[str, Any]],
    skills_by_plugin: dict[str, list[str]],
) -> int:
    count = 0
    for agent_file in sorted(root.glob("plugins/agent-plugins/*/agents/*.md")):
        metadata, body = _split_frontmatter(agent_file.read_text(encoding="utf-8"))
        slug = str(metadata.get("name") or agent_file.stem)
        cookbook = cookbooks.get(slug, {})
        connectors = _connectors_for_agent(metadata, cookbook)
        tools = _tools_for_agent(metadata, cookbook)
        repository.upsert_imported_agent(
            agent_id=f"{pack_id}:{slug}",
            pack_id=pack_id,
            source_slug=slug,
            name=_humanize(slug),
            description=str(metadata.get("description") or ""),
            agent_class=_agent_class_for(slug),
            system_prompt=body.strip(),
            guardrails=_extract_guardrails(body),
            skills=skills_by_plugin.get(slug, []),
            commands=[],
            required_provider_roles=_provider_roles_for(connectors),
            required_connectors=connectors,
            tool_policy=_tool_policy_for(tools, connectors),
            output_schema=_output_schema_for(cookbook),
            security_profile=_security_profile_for(body),
            status="imported",
            payload={
                "source_path": str(agent_file.relative_to(root)),
                "managed_model": cookbook.get("model"),
                "callable_agents": cookbook.get("callable_agents", []),
                "steering_examples": cookbook.get("steering_examples", []),
            },
        )
        count += 1
    return count


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    metadata = yaml.safe_load(parts[1]) or {}
    return metadata if isinstance(metadata, dict) else {}, parts[2]


def _read_json(path: Path, *, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _read_optional_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _plugin_slug_for(path: Path) -> str:
    parts = path.parts
    try:
        index = parts.index("agent-plugins")
    except ValueError:
        try:
            index = parts.index("vertical-plugins")
        except ValueError:
            return path.parent.parent.name
    return parts[index + 1]


def _connectors_for_agent(metadata: dict[str, Any], cookbook: dict[str, Any]) -> list[str]:
    connectors: set[str] = set()
    tools = str(metadata.get("tools") or "")
    connectors.update(match.group(1) for match in re.finditer(r"mcp__([A-Za-z0-9_-]+)__", tools))
    for server in cookbook.get("mcp_servers", []) or []:
        if isinstance(server, dict) and isinstance(server.get("name"), str):
            connectors.add(str(server["name"]))
    for tool in cookbook.get("tools", []) or []:
        if isinstance(tool, dict) and isinstance(tool.get("mcp_server_name"), str):
            connectors.add(str(tool["mcp_server_name"]))
    return sorted(connectors)


def _tools_for_agent(metadata: dict[str, Any], cookbook: dict[str, Any]) -> set[str]:
    tools = {tool.strip().lower() for tool in str(metadata.get("tools") or "").split(",")}
    for tool in cookbook.get("tools", []) or []:
        if not isinstance(tool, dict):
            continue
        for config in tool.get("configs", []) or []:
            if isinstance(config, dict) and config.get("enabled") is True:
                tools.add(str(config.get("name", "")).lower())
    return {tool for tool in tools if tool}


def _provider_roles_for(connectors: list[str]) -> dict[str, str]:
    if not connectors:
        return {}
    return {"financial_data": connectors[0]}


def _tool_policy_for(tools: set[str], connectors: list[str]) -> dict[str, bool]:
    return {
        "read_files": bool({"read", "grep", "glob"} & tools),
        "grep_files": "grep" in tools,
        "glob_files": "glob" in tools,
        "write_artifacts": bool({"write", "edit"} & tools),
        "edit_artifacts": "edit" in tools,
        "call_mcp": bool(connectors),
        "request_handoff": True,
    }


def _extract_guardrails(body: str) -> list[str]:
    guardrails: list[str] = []
    in_guardrails = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.lower().startswith("## guardrails"):
            in_guardrails = True
            continue
        if in_guardrails and stripped.startswith("## "):
            break
        if in_guardrails and stripped.startswith("-"):
            guardrails.append(stripped.lstrip("-").strip())
    return guardrails


def _output_schema_for(cookbook: dict[str, Any]) -> dict[str, Any]:
    schema = cookbook.get("output_schema")
    return dict(schema) if isinstance(schema, dict) else {}


def _security_profile_for(body: str) -> dict[str, bool]:
    lower_body = body.lower()
    return {
        "untrusted_document_awareness": "untrusted" in lower_body,
        "requires_human_review": "review" in lower_body or "approve" in lower_body,
        "broker_tools_allowed": False,
    }


def _agent_class_for(slug: str) -> str:
    if any(token in slug for token in ("kyc", "auditor")):
        return "compliance"
    if any(token in slug for token in ("reconciler", "closer")):
        return "finance_ops"
    if any(token in slug for token in ("valuation", "meeting")):
        return "wealth"
    return "research"


def _humanize(value: str) -> str:
    return " ".join(word.capitalize() for word in value.replace("_", "-").split("-"))
