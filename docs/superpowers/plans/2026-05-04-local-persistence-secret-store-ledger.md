# Local Persistence Secret Store Ledger Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the v1.2 backend foundation for durable provider configuration, secret references, private-office ledger events, graph-like entity relationships, and local snapshot manifests.

**Architecture:** Keep SQLite/SQLModel as the local system of record and introduce repository methods around small focused models. Store provider secrets by reference only, with a `SecretStore` protocol and environment/Mac Keychain implementations. Add a snapshot manifest generator that can later be encrypted and uploaded offsite.

**Tech Stack:** Python 3.12, SQLModel, SQLAlchemy, Pydantic, FastAPI, pytest, SQLite.

---

## File Structure

- Modify `/path/to/TradeMaster-workspace/TRADEMASTER_VISION.md`: record SQLite-first, pgvector migration, provider roles, Plaid banking, and high-risk AI-managed portfolio distinction.
- Modify `tradingagents/ui/models.py`: add provider config, private-office event, entity, edge, portfolio mandate, and snapshot manifest records.
- Modify `tradingagents/ui/repository.py`: add persistence methods for the new records.
- Modify `tradingagents/ui/providers.py`: expose durable provider descriptors with `secret_ref`, `control_mode`, and runtime configuration conversion.
- Create `tradingagents/ui/secrets.py`: define `SecretStore`, `EnvSecretStore`, and `MacKeychainSecretStore`.
- Create `tradingagents/ui/snapshots.py`: generate deterministic local backup snapshot manifests.
- Modify `tradingagents/ui/api.py`: expose provider config, ledger event, entity graph, and snapshot manifest endpoints.
- Create tests under `tests/ui/`.

## Task 1: Durable Provider Registry And Secret References

**Files:**
- Modify: `tradingagents/ui/models.py`
- Modify: `tradingagents/ui/repository.py`
- Modify: `tradingagents/ui/providers.py`
- Create: `tradingagents/ui/secrets.py`
- Test: `tests/ui/test_provider_registry.py`

- [ ] **Step 1: Write failing provider registry tests**

Create tests that configure Alpaca market data with `secret_ref="keychain:alpaca:paper"` and assert raw secret values are never stored. Add tests for provider role separation: Alpaca market data is agent-facing market data, Webull is human cockpit/handoff, and Plaid is read-only banking/account aggregation.

- [ ] **Step 2: Implement provider config model**

Add `ProviderConfigRecord` with provider id, role, status, enabled flag, capabilities JSON, primary use, secret ref, config JSON, health JSON, timestamps, and no raw secret column.

- [ ] **Step 3: Implement repository methods**

Add upsert/list/get methods for provider configs. Seed missing configs from static provider descriptors on first list.

- [ ] **Step 4: Implement secret store abstraction**

Add `SecretStore` protocol, `EnvSecretStore`, and `MacKeychainSecretStore`. The Mac implementation may shell out to `/usr/bin/security`; tests should use `EnvSecretStore`.

- [ ] **Step 5: Verify and commit**

Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_provider_registry.py -q` and commit.

## Task 2: Private-Office Event Ledger And Entity Graph

**Files:**
- Modify: `tradingagents/ui/models.py`
- Modify: `tradingagents/ui/repository.py`
- Test: `tests/ui/test_private_office_ledger.py`

- [ ] **Step 1: Write failing ledger and graph tests**

Add tests for append-only private-office events, listing events by entity id, creating entities for goals/assets/providers, and linking them with typed edges.

- [ ] **Step 2: Implement models**

Add `PrivateOfficeEventRecord`, `PrivateOfficeEntityRecord`, and `PrivateOfficeEdgeRecord`.

- [ ] **Step 3: Implement repository methods**

Add `append_private_office_event`, `list_private_office_events`, `upsert_private_office_entity`, `link_private_office_entities`, and `list_private_office_edges`.

- [ ] **Step 4: Verify and commit**

Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_private_office_ledger.py -q` and commit.

## Task 3: Portfolio Mandates And High-Risk Control Mode

**Files:**
- Modify: `tradingagents/ui/models.py`
- Modify: `tradingagents/ui/repository.py`
- Test: `tests/ui/test_portfolio_mandates.py`

- [ ] **Step 1: Write failing mandate tests**

Add tests that create a human-managed assisted mandate and an AI-managed high-risk mandate. Assert high-risk mandates require paper mode, caps, drawdown limit, turnover limit, and kill-switch field.

- [ ] **Step 2: Implement model and validation**

Add `PortfolioMandateRecord` and repository validation. High-risk mandates must not be active unless `paper_mode_required` and `kill_switch_enabled` are true.

- [ ] **Step 3: Verify and commit**

Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_portfolio_mandates.py -q` and commit.

## Task 4: Snapshot Manifest Skeleton

**Files:**
- Create: `tradingagents/ui/snapshots.py`
- Modify: `tradingagents/ui/models.py`
- Modify: `tradingagents/ui/repository.py`
- Test: `tests/ui/test_snapshots.py`

- [ ] **Step 1: Write failing snapshot tests**

Add tests that generate a manifest for the SQLite DB and at least one extra file, assert SHA-256 hashes are present, assert encryption mode is recorded, and assert no secret material is included.

- [ ] **Step 2: Implement snapshot manifest generator**

Add deterministic manifest creation with snapshot id, created timestamp, storage profile, database path, files, hashes, encryption mode, and offsite target label.

- [ ] **Step 3: Persist snapshot manifest**

Add `SnapshotManifestRecord` and repository methods to store/list manifests.

- [ ] **Step 4: Verify and commit**

Run `PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui/test_snapshots.py -q` and commit.

## Task 5: Minimal API Surface And Full Verification

**Files:**
- Modify: `tradingagents/ui/api.py`
- Modify: `tests/ui/test_api.py`

- [ ] **Step 1: Add API tests**

Add tests for listing durable provider config, updating a provider secret ref, appending a private-office event, and creating a snapshot manifest.

- [ ] **Step 2: Implement endpoints**

Add narrowly scoped endpoints under `/api/provider-configs`, `/api/private-office/events`, and `/api/snapshots`.

- [ ] **Step 3: Full verification**

Run:

```bash
npm --workspace apps/web run test
npm run web:lint
npm run web:build
PYTHONDONTWRITEBYTECODE=1 .venv/bin/pytest -p no:cacheprovider tests/ui -q
git diff --check
```

- [ ] **Step 4: Restart local server**

Restart port 3000 from the feature branch only after the full verification passes.

## Self-Review

Spec coverage: This plan covers SQLite-first provider configuration, secret references, event ledger, entity graph, high-risk portfolio mandates, snapshot manifests, and the minimal API surface. It intentionally does not implement live Alpaca/Webull/Plaid calls or autonomous trading.

Placeholder scan: No TBD/TODO/fill-in sections remain.

Type consistency: Provider config, private-office events, entity graph, portfolio mandates, and snapshot manifests are introduced before API usage.
