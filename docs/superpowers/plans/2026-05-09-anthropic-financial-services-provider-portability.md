# Anthropic Financial Services Provider-Portability Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Anthropic's Financial Services agent/skill pack into TradeMaster without making Claude the only runtime.

**Architecture:** Treat `anthropics/financial-services` as an importable domain-agent content pack: Markdown agent prompts, skill instructions, command definitions, MCP connector declarations, managed-agent cookbooks, subagent topology, steering examples, and safety notes. TradeMaster owns execution through its provider registry, LangGraph/A2A event model, agent workflow manifests, local ledger, and constrained A2UI renderer. Claude Managed Agents become one optional backend, not the product architecture.

**Tech Stack:** Python/FastAPI/SQLModel/SQLite backend, LangGraph orchestration, provider-neutral LLM client interface, MCP connector registry, React/Next.js Agent Builder, local event ledger, A2UI artifact renderer.

---

## Source Findings

The Anthropic repository is portable in content but Claude-specific in deployment wrapper.

Portable assets:

- `plugins/agent-plugins/<slug>/agents/<slug>.md`: named workflow agent prompt, workflow, guardrails, and skill list.
- `plugins/vertical-plugins/<vertical>/skills/**/SKILL.md`: domain methods for comps, DCF, earnings, sector primers, tax-loss harvesting, rebalancing, client reviews, KYC, fund-admin work, and document authoring.
- `plugins/vertical-plugins/<vertical>/commands/*.md`: slash-command style intent wrappers.
- `.mcp.json` files: connector declarations for Daloopa, Morningstar, S&P Global, FactSet, Moody's, MT Newswires, Aiera, LSEG, PitchBook, Chronograph, and Egnyte.
- `managed-agent-cookbooks/<slug>/agent.yaml`: orchestrator topology, subagent list, MCP needs, tool permissions, output schemas, and headless output policy.
- `steering-examples.json`: seed events for scheduled runs and workflow triggers.

Claude-specific assets:

- `model: claude-opus-4-7` in every cookbook.
- `agent_toolset_20260401`, Claude Managed Agents API, and `callable_agents`.
- Claude plugin marketplace metadata.
- Claude/Cowork assumptions for slash commands and plugin loading.
- Some prompt wording that says "Claude" or assumes Office/Cowork context.

Conclusion: We should not "run the repo" directly. We should ingest it, normalize it, and compile it into TradeMaster workflows.

## Provider-Portability Decision

We can make this work with any capable AI provider.

The safe route is a provider-neutral execution contract:

```text
Imported FSI pack
  -> normalized TradeMaster AgentPack
  -> provider-role requirements
  -> LangGraph / A2A orchestration
  -> LLM client chosen by provider registry
  -> constrained tools and MCP connectors
  -> event ledger + A2UI artifacts
```

Anthropic remains one selectable provider for research LLM roles. OpenAI, LM Studio, OpenRouter/Mistral, future Copilot/Codex developer-mode sources, and any OpenAI-compatible gateway can run the same normalized prompt/skill graph if they satisfy the required capabilities.

The hard line: execution agents do not inherit these research-agent prompts. Broker-adjacent execution remains deterministic, approval-gated, PyReason-policy checked, and separate from this imported FSI research pack.

## Target Product Shape

### Dashboard

Morning dashboard cards should surface overnight/scheduled outputs from imported FSI workflows:

- Market Researcher: sector/theme primers.
- Earnings Reviewer: earnings packet, model update summary, note draft.
- Wealth Management: rebalancing drift, tax-loss-harvesting opportunities, client report.
- Private Equity: deal screening, IC memo, portfolio-monitoring updates.
- Fund Admin / Operations: GL breaks, KYC flags, NAV/statement audit tasks.

### Agents

The Agents tab should show:

- Native TradingAgents research/execution roles.
- Imported FSI agents as "research/body-of-work agents".
- Status: imported, runnable, needs provider, needs connector, disabled by policy.
- Last run, next scheduled run, outputs, and required approvals.

### Agent Builder

The Agent Builder should expose imported FSI assets as draggable nodes:

- Agent nodes: Market Researcher, Earnings Reviewer, Model Builder, Pitch Agent, etc.
- Skill nodes: DCF, Comps, Sector Overview, Portfolio Rebalance, TLH, Financial Plan.
- Data nodes: FactSet, CapIQ/S&P, Morningstar, Plaid, Alpaca, SEC filings, local docs.
- Control nodes: human review, schema validator, untrusted-document isolation, write-holder boundary.

### Deep Research

Deep Research should be able to run an imported FSI workflow against a symbol, sector, theme, account, goal, asset, or uploaded document set, then render:

- Agent DAG.
- Individual agent reports.
- Sources and `[UNSOURCED]` flags.
- Review stops.
- Final memo/report/artifact.

### Settings

Settings should own provider routing:

- Research LLM role: Anthropic, OpenAI, LM Studio, OpenRouter, etc.
- Data connector role: FactSet, Morningstar, S&P Global, Daloopa, Alpaca, Plaid, SEC.
- Document store role: local files first, Egnyte later.
- Observability role: LangFuse.
- Execution LLM role: separate deterministic/symbolic path, not shared with imported research agents.

## Data Model Additions

### `AgentPackRecord`

Stores imported pack metadata.

Fields:

- `pack_id`: `anthropic-financial-services`
- `source_url`
- `source_commit`
- `license`
- `imported_at`
- `manifest`
- `status`

### `ImportedAgentRecord`

Stores normalized agent definitions.

Fields:

- `agent_id`
- `pack_id`
- `source_slug`
- `name`
- `description`
- `agent_class`: research, operations, finance_ops, wealth, compliance, execution_candidate
- `system_prompt`
- `guardrails`
- `skills`
- `commands`
- `required_provider_roles`
- `required_connectors`
- `tool_policy`
- `output_schema`
- `security_profile`
- `status`

### `ImportedSkillRecord`

Stores normalized skill instructions and references.

Fields:

- `skill_id`
- `pack_id`
- `source_path`
- `name`
- `description`
- `instructions_markdown`
- `references`
- `scripts`
- `artifact_requirements`
- `status`

### `McpConnectorRecord`

Stores normalized MCP connector declarations separately from LLM providers.

Fields:

- `connector_id`
- `name`
- `url`
- `provider_id`
- `required_secret_ref`
- `capabilities`
- `health`
- `enabled`
- `subscription_required`

### `AgentCapabilityRequirement`

Maps a workflow to provider features.

Examples:

- `llm.structured_output`
- `llm.long_context`
- `llm.tool_calling`
- `llm.json_schema_output`
- `tool.read_only_files`
- `tool.write_artifact`
- `mcp.factset`
- `review.human_stop`

## Runtime Design

### Provider-Neutral LLM Contract

Add a single `LlmClient` capability contract rather than branching runtime logic by vendor.

The contract should support:

- `generate_text`
- `generate_json`
- `stream_events`
- `tool_calling` when provider supports it
- `json_schema_output` when provider supports it
- `max_context_tokens`
- `cost_metadata`
- `provider_model_id`

Provider adapters:

- Anthropic native.
- OpenAI Responses-compatible.
- OpenAI-compatible local gateway for LM Studio.
- OpenRouter-compatible adapter for Mistral and others.
- Existing Codex CLI developer-mode adapter stays test-only.

If a provider lacks strict JSON schema output, TradeMaster wraps the model with validation/retry and marks the run as `structured_output_emulated`.

### Tool Policy

Normalize Claude's `agent_toolset_20260401` into TradeMaster policy names:

- `read_files`
- `grep_files`
- `glob_files`
- `write_artifacts`
- `edit_artifacts`
- `call_mcp`
- `request_handoff`

Default policy:

- Research readers: read-only.
- Untrusted-document readers: read-only, no external connectors, schema-only output.
- Writers: write artifacts only, no direct untrusted-document access.
- Connectors: read-only unless explicitly approved.
- Broker tools: not available to imported FSI agents.

### Orchestration

Compile each imported `agent.yaml` into a TradeMaster `AgentWorkflowRecord`:

- Orchestrator node.
- Subagent nodes.
- MCP/data connector nodes.
- Human review stop nodes.
- Schema validator nodes.
- A2A handoff edges.
- A2UI artifact nodes.

Use LangGraph for execution and TradeMaster `RunEventRecord` for the canonical event stream. The Anthropic `handoff_request` text pattern becomes an internal typed A2A event, not arbitrary JSON parsed from model output.

### Security Translation

Preserve the repo's strongest pattern: untrusted-document isolation.

For each imported workflow:

- Mark which nodes may touch untrusted input.
- Mark which nodes may write files.
- Never allow the same node to read untrusted docs and write final artifacts unless manually approved.
- Validate subagent outputs with JSON schema when the source cookbook provides one.
- Emit ledger events for each handoff, schema rejection, provider access, connector call, and human review checkpoint.

## Integration Phases

### Phase 1: Importer and Catalog

Goal: Make the pack visible and queryable without running it.

- [ ] Create `tradingagents/ui/agent_packs/models.py`.
- [ ] Create `tradingagents/ui/agent_packs/importer.py`.
- [ ] Parse:
  - `.claude-plugin/marketplace.json`
  - `plugins/agent-plugins/**/.claude-plugin/plugin.json`
  - `plugins/agent-plugins/**/agents/*.md`
  - `plugins/vertical-plugins/**/commands/*.md`
  - `plugins/**/skills/**/SKILL.md`
  - `plugins/**/.mcp.json`
  - `managed-agent-cookbooks/**/agent.yaml`
  - `managed-agent-cookbooks/**/steering-examples.json`
- [ ] Store normalized records in SQLite.
- [ ] Add API:
  - `GET /api/agent-packs`
  - `POST /api/agent-packs/import`
  - `GET /api/imported-agents`
  - `GET /api/imported-skills`
  - `GET /api/mcp-connectors`
- [ ] Add tests with a tiny fixture pack that includes one agent, one skill, one command, one MCP connector, and one subagent cookbook.

### Phase 2: Provider Capability Resolver

Goal: Decide whether a workflow can run on Anthropic, OpenAI, LM Studio, OpenRouter, or another provider.

- [ ] Extend provider descriptors with capability flags:
  - `structured_output`
  - `json_schema_output`
  - `tool_calling`
  - `streaming`
  - `long_context`
  - `vision`
  - `document_input`
- [ ] Add `provider_capability_resolver.py`.
- [ ] Add API:
  - `POST /api/imported-agents/{agent_id}/capability-check`
- [ ] Return:
  - runnable provider choices
  - missing capabilities
  - emulation path when available
  - blocked reasons
- [ ] UI: Settings shows which provider can run each imported agent.

### Phase 3: Prompt and Skill Compiler

Goal: Compile Claude-style agents/skills into provider-neutral runtime prompts.

- [ ] Create `tradingagents/ui/agent_packs/compiler.py`.
- [ ] Convert each imported agent into:
  - system prompt
  - task prompt template
  - skill bundle
  - source/guardrail reminders
  - output expectations
  - review checkpoints
- [ ] Strip or rewrite Claude/Cowork-specific assumptions.
- [ ] Preserve original text in `source_prompt` for audit.
- [ ] Add prompt snapshots to tests so provider-neutral compilation is deterministic.

### Phase 4: MCP Connector Registry

Goal: Bring the Anthropic connector list into our provider settings without assuming every connector is configured.

- [ ] Import MCP declarations as `McpConnectorRecord`.
- [ ] Map connectors to provider roles:
  - `financial_data`
  - `issuer_filings`
  - `news_events`
  - `research_platform`
  - `document_store`
  - `portfolio_accounting`
- [ ] Health check only verifies configured URL/secret presence unless the provider supports a safe read-only health endpoint.
- [ ] UI: Settings gets a "Data Connectors" section separate from LLM providers.
- [ ] Default all premium connectors to disabled/planned.

### Phase 5: Workflow Compiler to LangGraph

Goal: Run one imported workflow in TradeMaster without Claude Managed Agents.

Start with `market-researcher`.

- [ ] Compile cookbook topology into `AgentWorkflowRecord`.
- [ ] Map subagents to LangGraph nodes.
- [ ] Map subagent outputs to typed event payloads.
- [ ] Enforce tool policy per node.
- [ ] Emit A2A handoff events instead of parsing handoff JSON from raw text.
- [ ] Add review-stop nodes after comps and draft note, matching source guardrails.
- [ ] Add tests for:
  - node graph generation
  - tool policy enforcement
  - required connector detection
  - provider fallback selection
  - schema validation failure

### Phase 6: Agent Builder UI

Goal: Make imported agents and skills first-class draggable building blocks.

- [ ] Extend `apps/web/src/lib/agent-builder.ts` node model with:
  - `sourcePack`
  - `capabilityRequirements`
  - `toolPolicy`
  - `requiredConnectors`
  - `securityProfile`
- [ ] Add imported-agent and imported-skill palette groups.
- [ ] Inspector shows:
  - original source path
  - provider compatibility
  - required connectors
  - guardrails
  - review stops
  - write/read isolation status
- [ ] Saving a workflow persists imported nodes and the compiled graph payload.

### Phase 7: Deep Research Runner

Goal: Let the user run imported FSI research workflows and read agent-level reports.

- [ ] Add endpoint:
  - `POST /api/imported-agents/{agent_id}/runs`
- [ ] Support event stream:
  - node started
  - connector called
  - schema validated
  - human review required
  - artifact written
  - handoff requested
  - final report ready
- [ ] Render A2UI report surfaces:
  - source table
  - comps table
  - review checkpoint card
  - document artifact card
  - final memo/report reader
- [ ] Store every run in the same event ledger as TradingAgents runs.

### Phase 8: Scheduling and Morning Briefs

Goal: Use imported agents as always-on morning/evening research workers.

- [ ] Extend report schedules to target `agent_id` and `workflow_id`, not only symbol.
- [ ] Add schedule scopes:
  - symbol
  - sector
  - portfolio
  - account
  - asset
  - goal
  - document set
- [ ] Dashboard shows scheduled imported-agent outputs beside TradingAgents outputs.
- [ ] The Agents tab shows active schedules and recent failures.

### Phase 9: Wealth / Tax / Portfolio Integration

Goal: Connect the imported wealth-management assets to our private-office thesis.

Prioritize:

- `portfolio-rebalance`
- `tax-loss-harvesting`
- `client-report`
- `financial-plan`

TradeMaster adaptations:

- Replace generic "client" language with Michael/private-office account context.
- Use Plaid holdings/transactions and Alpaca/Webull human-managed positions as read-only inputs.
- Add tax/legal disclaimers and human review stops.
- Emit recommendations only; no broker action.
- Link outputs to goals, assets, mandates, and tax issues in the private-office graph.

### Phase 10: Optional Claude Managed Agent Backend

Goal: Keep Anthropic's native managed-agent route available but isolated.

- [ ] Add provider role: `managed_agent_runtime`.
- [ ] Allow `anthropic-managed-agent` as an optional runtime for an imported workflow.
- [ ] Never require it.
- [ ] Store managed-agent IDs as provider config, not in imported pack records.
- [ ] Keep all outputs mirrored into TradeMaster's run/event/artifact ledger.

## First Useful Slice

The first implementation slice should be small:

1. Import and display the pack catalog.
2. Normalize `market-researcher`.
3. Show it in Agent Builder as an imported agent with required FactSet/CapIQ connectors and provider capability needs.
4. Compile it to a draft workflow without running external connectors.
5. Run it in dry-run mode against local mocked connector data through the selected `research_llm` provider.
6. Produce an A2UI research note card and individual subagent reports.

This proves portability before we touch premium data providers or Claude Managed Agents.

## Non-Negotiables

- No imported FSI agent gets broker tools.
- No raw API keys in SQLite.
- No arbitrary UI from model output.
- No arbitrary connector calls without provider registry approval.
- No parsing model-emitted JSON handoff blobs as authoritative system events.
- No final recommendations presented as financial, tax, legal, or accounting advice.
- All generated work product is draft-for-review.
- Every provider call, connector call, handoff, review stop, artifact, and failure gets ledgered.

## Files to Create or Modify

Backend:

- Create `tradingagents/ui/agent_packs/__init__.py`
- Create `tradingagents/ui/agent_packs/models.py`
- Create `tradingagents/ui/agent_packs/importer.py`
- Create `tradingagents/ui/agent_packs/compiler.py`
- Create `tradingagents/ui/agent_packs/capabilities.py`
- Create `tradingagents/ui/agent_packs/runtime.py`
- Modify `tradingagents/ui/models.py`
- Modify `tradingagents/ui/repository.py`
- Modify `tradingagents/ui/api.py`
- Modify `tradingagents/ui/providers.py`

Frontend:

- Modify `apps/web/src/lib/types.ts`
- Modify `apps/web/src/lib/api.ts`
- Modify `apps/web/src/lib/agent-builder.ts`
- Modify `apps/web/src/components/AgentBuilderWorkspace.tsx`
- Modify `apps/web/src/components/AgentsWorkspace.tsx`
- Modify `apps/web/src/components/DeepResearchWorkspace.tsx`
- Modify `apps/web/src/components/SettingsDrawer.tsx`

Tests:

- Create `tests/ui/test_agent_pack_importer.py`
- Create `tests/ui/test_agent_pack_compiler.py`
- Create `tests/ui/test_imported_agent_runtime.py`
- Create `tests/fixtures/agent_packs/mini_financial_services/**`
- Modify `apps/web/src/lib/agent-builder.test.ts`
- Modify `apps/web/src/components/AgentBuilderWorkspace.test.ts`
- Modify `apps/web/src/components/SettingsDrawer.test.ts`

Docs:

- Update `docs/TRADEMASTER_ROADMAP.md`
- Update `docs/LOCAL_SERVER.md`

## Test Commands

Backend:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_agent_pack_importer.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_agent_pack_compiler.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_imported_agent_runtime.py -q
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui -q
```

Frontend:

```bash
npm --workspace apps/web test
npm run web:lint
NEXT_PUBLIC_API_BASE='http://127.0.0.1:8797' TRADEMASTER_API_BASE='http://127.0.0.1:8797' npm run web:build
```

Manual browser check:

- Open `http://127.0.0.1:3000/`.
- Go to Settings and confirm imported connectors are separate from LLM providers.
- Go to Agent Builder and confirm imported Market Researcher appears as a node.
- Save a draft imported workflow.
- Go to Deep Research and run a dry-run Market Researcher workflow.
- Confirm individual subagent reports and final A2UI report card render.

## Open Questions

- Should imported pack source live as a git submodule, vendored copy, or on-demand import from a checked-out path?
- Should we import all skills initially or only the workflows that match TradeMaster's current private-office roadmap?
- Do we want a local document-store connector first, before any premium research provider MCP?
- Which provider should be the first portability proof: OpenAI, LM Studio, or OpenRouter/Mistral?

## Recommendation

Use a local checked-out path import first, not a submodule. Import only `market-researcher`, `earnings-reviewer`, and the wealth-management skills in the first round. Prove the runtime with LM Studio and OpenAI-compatible routing before enabling Anthropic Managed Agents. Then add premium MCP connectors one at a time behind Settings and health checks.
