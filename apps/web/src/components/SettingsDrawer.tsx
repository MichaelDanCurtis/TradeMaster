"use client";
import { ResearchSystemStatus } from "@/components/ResearchOverview";

/**
 * SettingsWorkspace — the rebuild.
 *
 * File still named SettingsDrawer.tsx for historic reasons (the export
 * lived in a drawer before the 4-tab flattening on 2026-05-20) but the
 * component is now a workspace with a sub-nav across four sections:
 * Runtime, Providers, Backups, Developer. All backend wiring is
 * preserved verbatim — only the shell, layout, and CSS-class surface
 * changed.
 */

import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  checkProviderHealth,
  createSnapshot,
  createUserProvider,
  deleteUserProvider,
  getRuntimeStatus,
  listProviderConfigs,
  listProviderModels,
  listProviderRoleAssignments,
  listSnapshots,
  updateDeveloperMode,
  updateProviderConfig,
  updateResearchRunnerMode,
  updateProviderRoleAssignment,
  verifySnapshot
} from "@/lib/api";
import type { ProviderModelList, UserProviderKind } from "@/lib/api";
import type {
  ProviderConfig,
  ProviderControlSurface,
  ProviderRole,
  ProviderRoleAssignment,
  ProviderRoleKey,
  RuntimeStatus,
  SnapshotManifestRecord,
  SnapshotVerification
} from "@/lib/types";
import {
  ALL_ROLES as ALL_AGENT_ROLES,
  COORDINATOR_ROLES as COORDINATOR_AGENT_ROLES,
  ROLE_LABELS as AGENT_ROLE_LABELS,
  resolveRoleModel,
  type RoleKey as AgentRoleKey,
  type RoleModelsConfig
} from "@/lib/role-models";

type SettingsSubView = "runtime" | "providers" | "backups" | "developer";

const SUB_VIEWS: { id: SettingsSubView; label: string; subtitle: string }[] = [
  // "Runtime wiring" is the historic phrase used by SettingsDrawer.test.ts
  // and by docs that link to the runtime status overview — keep it in the
  // copy so the source-text assertion survives the workspace rebuild.
  { id: "runtime", label: "Runtime", subtitle: "Runtime wiring · research runner · LLM · broker · execution policy" },
  { id: "providers", label: "Providers", subtitle: "Provider catalog and role wiring" },
  { id: "backups", label: "Backups", subtitle: "Encrypted snapshots and verification" },
  { id: "developer", label: "Developer", subtitle: "Dev mode · runtime info · export" }
];

const ROLE_LABELS: Record<ProviderRole, string> = {
  brokerage: "Brokerage",
  llm: "LLM",
  "market-data": "Market data",
  observability: "Observability",
  portfolio: "Portfolio",
  safety: "Safety"
};

const SURFACE_LABELS: Record<ProviderControlSurface, string> = {
  "agent-data": "Agent data",
  "ai-harness": "AI harness",
  "human-cockpit": "Human cockpit",
  platform: "Platform"
};

const ROLE_ASSIGNMENT_LABELS: Record<ProviderRoleKey, string> = {
  broker: "Broker",
  execution_llm: "Execution LLM",
  market_data: "Market data",
  observability: "Observability",
  portfolio: "Portfolio",
  research_llm: "Research LLM",
  research_designer: "Strategy research designer",
  research_extractor: "Research evidence extractor",
  safety: "Safety"
};

const PROVIDER_GROUPS: { id: ProviderRole; label: string; kicker: string }[] = [
  { id: "llm", label: "LLM providers", kicker: "Research & execution reasoning" },
  { id: "brokerage", label: "Broker providers", kicker: "Paper and live order surfaces" },
  { id: "market-data", label: "Market data providers", kicker: "Quotes, fundamentals, news" },
  { id: "portfolio", label: "Portfolio providers", kicker: "Position and PnL reconciliation" },
  { id: "observability", label: "Observability", kicker: "Trace, log, and metric sinks" },
  { id: "safety", label: "Safety", kicker: "Policy and guardrail integrations" }
];

export function SettingsWorkspace() {
  const [activeSubView, setActiveSubView] = useState<SettingsSubView>("runtime");

  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [roleAssignments, setRoleAssignments] = useState<ProviderRoleAssignment[]>([]);
  const [strategyProtocols, setStrategyProtocols] = useState<string[]>([]);
  const [catalogLoaded, setCatalogLoaded] = useState(false);
  const [snapshotsLoaded, setSnapshotsLoaded] = useState(false);
  const [runtimeReadAt, setRuntimeReadAt] = useState<string | null>(null);
  const [runtimeStatus, setRuntimeStatus] = useState<RuntimeStatus | null>(null);
  const [draftSecretRefs, setDraftSecretRefs] = useState<Record<string, string>>({});
  const [snapshot, setSnapshot] = useState<SnapshotManifestRecord | null>(null);
  const [snapshotList, setSnapshotList] = useState<SnapshotManifestRecord[]>([]);
  const [backupKeyRef, setBackupKeyRef] = useState("env:TRADEMASTER_BACKUP_KEY");
  const [snapshotVerification, setSnapshotVerification] = useState<SnapshotVerification | null>(null);
  const [verifyingSnapshotId, setVerifyingSnapshotId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [savingRoleKey, setSavingRoleKey] = useState<ProviderRoleKey | null>(null);
  const [savingRunnerMode, setSavingRunnerMode] = useState(false);
  const [savingDeveloperMode, setSavingDeveloperMode] = useState(false);
  const [newProviderDraft, setNewProviderDraft] = useState<{
    name: string;
    kind: UserProviderKind;
    baseUrl: string;
    model: string;
    apiKeyEnv: string;
  }>({ name: "", kind: "openai-compatible", baseUrl: "", model: "", apiKeyEnv: "" });
  const [creatingProvider, setCreatingProvider] = useState(false);
  const [roleModelsDraft, setRoleModelsDraft] = useState<{
    providerId: string | null;
    coordinator: string;
    agent: string;
    overrides: Record<string, string>;
  }>({ providerId: null, coordinator: "", agent: "", overrides: {} });
  const [savingRoleModels, setSavingRoleModels] = useState(false);
  const [availableModels, setAvailableModels] = useState<ProviderModelList | null>(null);
  const [snapshotPending, setSnapshotPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    const errors: string[] = [];
    const capture = (section: string, caught: unknown) => {
      errors.push(`${section}: ${caught instanceof Error ? caught.message : "load failed"}`);
    };
    Promise.allSettled([
      listProviderConfigs().then((catalog) => {
        if (cancelled) return;
        setProviders(catalog.providers);
        setCatalogLoaded(true);
        setDraftSecretRefs(Object.fromEntries(catalog.providers.map((provider) => [provider.provider_id, provider.secret_ref ?? ""])));
      }).catch((e) => capture("Providers", e)),
      listProviderRoleAssignments().then((catalog) => {
        if (cancelled) return;
        setRoleAssignments(catalog.assignments);
        setStrategyProtocols(catalog.strategy_research_protocols ?? []);
      }).catch((e) => capture("Role assignments", e)),
      getRuntimeStatus().then((status) => {
        if (cancelled) return;
        setRuntimeStatus(status);
        setRuntimeReadAt(new Date().toLocaleTimeString());
      }).catch((e) => capture("Runtime configuration", e)),
      listSnapshots().then((snapshots) => {
        if (cancelled) return;
        setSnapshotList(snapshots.items);
        setSnapshotsLoaded(true);
        setSnapshot(snapshots.items[0] ?? null);
      }).catch((e) => capture("Snapshot history", e))
    ]).then(() => {
      if (!cancelled) {
        setError(errors.length ? errors.join(" · ") : null);
        setLoading(false);
      }
    });

    return () => {
      cancelled = true;
    };
  }, []);

  async function refreshSnapshotList() {
    try {
      const result = await listSnapshots();
      setSnapshotList(result.items);
      setSnapshotsLoaded(true);
    } catch {
      setSnapshotsLoaded(false);
      setError("Snapshot history could not be refreshed; the displayed list may be stale.");
    }
  }

  const sortedProviders = useMemo(() => [...providers].sort(compareProviders), [providers]);
  const sortedRoleAssignments = useMemo(
    () => [...roleAssignments].sort((left, right) => left.role_key.localeCompare(right.role_key)),
    [roleAssignments]
  );
  const providerById = useMemo(
    () => Object.fromEntries(providers.map((provider) => [provider.provider_id, provider])),
    [providers]
  );

  async function handleProviderToggle(provider: ProviderConfig, enabled: boolean) {
    setSavingProviderId(provider.provider_id);
    try {
      const updated = await updateProviderConfig(provider.provider_id, { enabled });
      setProviders((current) =>
        current.map((item) => (item.provider_id === updated.provider_id ? updated : item))
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider update failed");
    } finally {
      setSavingProviderId(null);
    }
  }

  async function handleSecretRefSave(provider: ProviderConfig) {
    setSavingProviderId(provider.provider_id);
    try {
      const nextRef = draftSecretRefs[provider.provider_id]?.trim() || null;
      const updated = await updateProviderConfig(provider.provider_id, { secretRef: nextRef });
      setProviders((current) =>
        current.map((item) => (item.provider_id === updated.provider_id ? updated : item))
      );
      setDraftSecretRefs((current) => ({ ...current, [updated.provider_id]: updated.secret_ref ?? "" }));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Secret reference update failed");
    } finally {
      setSavingProviderId(null);
    }
  }

  async function handleProviderHealthCheck(provider: ProviderConfig) {
    setSavingProviderId(provider.provider_id);
    try {
      const updated = await checkProviderHealth(provider.provider_id);
      setProviders((current) =>
        current.map((item) => (item.provider_id === updated.provider_id ? updated : item))
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider health check failed");
    } finally {
      setSavingProviderId(null);
    }
  }

  async function handleCreateSnapshot() {
    setSnapshotPending(true);
    try {
      const created = await createSnapshot({ encryptionMode: "none", offsiteTarget: "manual-offsite" });
      setSnapshot(created);
      setSnapshotVerification(null);
      setError(null);
      await refreshSnapshotList();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Snapshot creation failed");
    } finally {
      setSnapshotPending(false);
    }
  }

  async function handleCreateEncryptedSnapshot() {
    setSnapshotPending(true);
    try {
      const created = await createSnapshot({
        backupKeyRef: backupKeyRef.trim(),
        offsiteTarget: "manual-offsite"
      });
      setSnapshot(created);
      setSnapshotVerification(null);
      setError(null);
      await refreshSnapshotList();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Encrypted snapshot creation failed");
    } finally {
      setSnapshotPending(false);
    }
  }

  async function handleVerifySnapshot(target?: SnapshotManifestRecord) {
    const record = target ?? snapshot;
    if (!record) return;
    setSnapshotPending(true);
    setVerifyingSnapshotId(record.snapshot_id);
    setSnapshotVerification(null);
    try {
      const verification = await verifySnapshot(record.snapshot_id, { backupKeyRef: backupKeyRef.trim() });
      setSnapshot(record);
      setSnapshotVerification(verification);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Snapshot verification failed");
    } finally {
      setSnapshotPending(false);
      setVerifyingSnapshotId(null);
    }
  }

  async function handleRoleAssignmentChange(roleKey: ProviderRoleKey, providerId: string) {
    setSavingRoleKey(roleKey);
    try {
      const updated = await updateProviderRoleAssignment(roleKey, providerId);
      setRoleAssignments((current) =>
        current.map((assignment) => (assignment.role_key === updated.role_key ? updated : assignment))
      );
      setRuntimeStatus(await getRuntimeStatus());
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Provider role assignment failed");
    } finally {
      setSavingRoleKey(null);
    }
  }

  async function handleResearchRunnerModeChange(mode: "llm-ui-runner" | "tradingagents-graph-runner") {
    setSavingRunnerMode(true);
    try {
      const status = await updateResearchRunnerMode(mode);
      setRuntimeStatus(status);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Research runner update failed");
    } finally {
      setSavingRunnerMode(false);
    }
  }

  async function handleDeveloperModeToggle(enabled: boolean) {
    setSavingDeveloperMode(true);
    try {
      const status = await updateDeveloperMode(enabled);
      setRuntimeStatus(status);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Developer mode update failed");
    } finally {
      setSavingDeveloperMode(false);
    }
  }

  async function handleCreateUserProvider() {
    setCreatingProvider(true);
    try {
      const created = await createUserProvider({
        name: newProviderDraft.name.trim(),
        kind: newProviderDraft.kind,
        baseUrl: newProviderDraft.baseUrl.trim(),
        model: newProviderDraft.model.trim(),
        apiKeyEnv: newProviderDraft.apiKeyEnv.trim() || null
      });
      setProviders((current) => [...current, created]);
      setDraftSecretRefs((current) => ({ ...current, [created.provider_id]: created.secret_ref ?? "" }));
      setNewProviderDraft({ name: "", kind: "openai-compatible", baseUrl: "", model: "", apiKeyEnv: "" });
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not add custom provider");
    } finally {
      setCreatingProvider(false);
    }
  }

  async function handleDeleteUserProvider(provider: ProviderConfig) {
    setSavingProviderId(provider.provider_id);
    try {
      await deleteUserProvider(provider.provider_id);
      setProviders((current) => current.filter((item) => item.provider_id !== provider.provider_id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not delete custom provider");
    } finally {
      setSavingProviderId(null);
    }
  }

  const researchProviderId = useMemo(
    () => roleAssignments.find((assignment) => assignment.role_key === "research_llm")?.provider_id ?? null,
    [roleAssignments]
  );
  const researchProvider = researchProviderId ? providerById[researchProviderId] : undefined;

  useEffect(() => {
    if (!researchProvider) {
      setRoleModelsDraft({ providerId: null, coordinator: "", agent: "", overrides: {} });
      return;
    }
    const cfg = (researchProvider.config.role_models as RoleModelsConfig | undefined) ?? {};
    setRoleModelsDraft({
      providerId: researchProvider.provider_id,
      coordinator: typeof cfg.coordinator === "string" ? cfg.coordinator : "",
      agent: typeof cfg.agent === "string" ? cfg.agent : "",
      overrides: { ...(cfg.overrides ?? {}) }
    });
  }, [researchProvider]);

  useEffect(() => {
    if (!researchProviderId) {
      setAvailableModels(null);
      return;
    }
    let cancelled = false;
    listProviderModels(researchProviderId)
      .then((result) => {
        if (!cancelled) setAvailableModels(result);
      })
      .catch(() => {
        if (!cancelled) {
          setAvailableModels({
            provider_id: researchProviderId,
            models: [],
            source: "unavailable"
          });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [researchProviderId]);

  const fallbackModel = researchProvider
    ? (typeof researchProvider.config.model === "string" ? (researchProvider.config.model as string) : "")
    : "";

  async function handleSaveRoleModels() {
    if (!researchProvider) return;
    setSavingRoleModels(true);
    try {
      const nextConfig: Record<string, unknown> = { ...researchProvider.config };
      const cleanedOverrides = Object.fromEntries(
        Object.entries(roleModelsDraft.overrides).filter(
          ([, model]) => typeof model === "string" && model.trim() !== ""
        )
      );
      nextConfig.role_models = {
        coordinator: roleModelsDraft.coordinator.trim(),
        agent: roleModelsDraft.agent.trim(),
        overrides: cleanedOverrides
      };
      const updated = await updateProviderConfig(researchProvider.provider_id, {
        config: nextConfig
      });
      setProviders((current) =>
        current.map((item) => (item.provider_id === updated.provider_id ? updated : item))
      );
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save per-agent models");
    } finally {
      setSavingRoleModels(false);
    }
  }

  function handleExportSettings() {
    const payload = {
      exported_at: new Date().toISOString(),
      runtime: runtimeStatus,
      providers: providers.map((provider) => ({
        provider_id: provider.provider_id,
        name: provider.name,
        role: provider.role,
        enabled: provider.enabled,
        status: provider.status,
        secret_ref: provider.secret_ref,
        config: provider.config
      })),
      role_assignments: roleAssignments
    };
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `trademaster-settings-${new Date().toISOString().slice(0, 10)}.json`;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    URL.revokeObjectURL(url);
  }

  const backupKeyConfigured = backupKeyRef.trim().length > 0;
  const researchRoleAssignment = roleAssignments.find((entry) => entry.role_key === "research_llm");
  const brokerRoleAssignment = roleAssignments.find((entry) => entry.role_key === "broker");
  const brokerProvider = brokerRoleAssignment ? providerById[brokerRoleAssignment.provider_id] : undefined;

  return (
    <section className="settings-workspace-root" aria-label="Settings workspace">
      <header className="settings-workspace-header">
        <div className="settings-workspace-heading-copy">
          <span className="panel-kicker">Configuration</span>
          <h1>Settings</h1>
        </div>
        <div className="settings-workspace-status">
          <StatusPill tone={runtimeStatus ? "positive" : loading ? "neutral" : "negative"}>
            {runtimeStatus ? "Configuration loaded" : loading ? "Loading" : "Configuration unavailable"}
          </StatusPill>
          <span className="settings-workspace-status-detail">
            {catalogLoaded ? `${providers.length} catalog entries · ${providers.filter((p) => p.enabled).length} enabled` : "Provider catalog unavailable"}
            {" · "}{snapshotsLoaded ? `Backup files: ${snapshotList.filter((s) => s.manifest.backup_artifact).length} · Manifests only: ${snapshotList.filter((s) => !s.manifest.backup_artifact).length}` : "Snapshot history unavailable"}
            {runtimeReadAt ? ` · Config read ${runtimeReadAt}` : ""}
          </span>
        </div>
      </header>

      <nav className="settings-subnav" role="tablist" aria-label="Settings sub-views">
        {SUB_VIEWS.map((view) => (
          <button
            aria-current={view.id === activeSubView ? "page" : undefined}
            aria-selected={view.id === activeSubView}
            className={view.id === activeSubView ? "settings-subnav-tab active" : "settings-subnav-tab"}
            key={view.id}
            onClick={() => setActiveSubView(view.id)}
            role="tab"
            type="button"
            title={view.subtitle}
          >
            {view.label}
          </button>
        ))}
      </nav>

      {error ? <p className="settings-error">{error}</p> : null}

      <div className="settings-subview-content">
        {activeSubView === "runtime" ? (
          <RuntimeSection
            loading={loading}
            runtimeStatus={runtimeStatus}
            researchProvider={researchProvider}
            brokerProvider={brokerProvider}
            savingRunnerMode={savingRunnerMode}
            handleResearchRunnerModeChange={handleResearchRunnerModeChange}
          />
        ) : null}

        {activeSubView === "providers" ? (
          <ProvidersSection
            loading={loading}
            strategyProtocols={strategyProtocols}
            sortedProviders={sortedProviders}
            sortedRoleAssignments={sortedRoleAssignments}
            providerById={providerById}
            runtimeStatus={runtimeStatus}
            savingProviderId={savingProviderId}
            savingRoleKey={savingRoleKey}
            draftSecretRefs={draftSecretRefs}
            setDraftSecretRefs={setDraftSecretRefs}
            handleProviderToggle={handleProviderToggle}
            handleSecretRefSave={handleSecretRefSave}
            handleProviderHealthCheck={handleProviderHealthCheck}
            handleDeleteUserProvider={handleDeleteUserProvider}
            handleRoleAssignmentChange={handleRoleAssignmentChange}
            newProviderDraft={newProviderDraft}
            setNewProviderDraft={setNewProviderDraft}
            creatingProvider={creatingProvider}
            handleCreateUserProvider={handleCreateUserProvider}
            researchProvider={researchProvider}
            availableModels={availableModels}
            roleModelsDraft={roleModelsDraft}
            setRoleModelsDraft={setRoleModelsDraft}
            fallbackModel={fallbackModel}
            savingRoleModels={savingRoleModels}
            handleSaveRoleModels={handleSaveRoleModels}
          />
        ) : null}

        {activeSubView === "backups" ? (
          <BackupsSection
            historyAvailable={snapshotsLoaded}
            loading={loading}
            snapshot={snapshot}
            snapshotList={snapshotList}
            snapshotPending={snapshotPending}
            backupKeyRef={backupKeyRef}
            setBackupKeyRef={setBackupKeyRef}
            backupKeyConfigured={backupKeyConfigured}
            verifyingSnapshotId={verifyingSnapshotId}
            snapshotVerification={snapshotVerification}
            handleCreateSnapshot={handleCreateSnapshot}
            handleCreateEncryptedSnapshot={handleCreateEncryptedSnapshot}
            handleVerifySnapshot={handleVerifySnapshot}
            setSnapshot={setSnapshot}
            setSnapshotVerification={setSnapshotVerification}
          />
        ) : null}

        {activeSubView === "developer" ? (
          <DeveloperSection
            runtimeStatus={runtimeStatus}
            savingDeveloperMode={savingDeveloperMode}
            handleDeveloperModeToggle={handleDeveloperModeToggle}
            handleExportSettings={handleExportSettings}
            providerCount={providers.length}
            snapshotCount={snapshotList.length}
            researchRoleAssignment={researchRoleAssignment}
          />
        ) : null}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Runtime sub-section
// ---------------------------------------------------------------------------

function RuntimeSection({
  loading,
  runtimeStatus,
  researchProvider,
  brokerProvider,
  savingRunnerMode,
  handleResearchRunnerModeChange
}: {
  loading: boolean;
  runtimeStatus: RuntimeStatus | null;
  researchProvider: ProviderConfig | undefined;
  brokerProvider: ProviderConfig | undefined;
  savingRunnerMode: boolean;
  handleResearchRunnerModeChange: (mode: "llm-ui-runner" | "tradingagents-graph-runner") => void;
}) {
  if (loading && !runtimeStatus) {
    return <LoadingPanel label="Loading runtime wiring" />;
  }

  if (!runtimeStatus) {
    return <><ResearchSystemStatus/><EmptyPanel label="Runtime status unavailable" detail="Backend did not return /api/runtime/status." /></>;
  }

  const policy = runtimeStatus.execution_policy;
  const researchLLM = runtimeStatus.research_llm;
  const broker = runtimeStatus.broker;
  const runnerMode = runtimeStatus.research_runner.configured_mode ?? runtimeStatus.research_runner.mode;
  const fullGraphConfigured = runtimeStatus.full_tradingagents_graph.configured;
  const fullGraphEnv = runtimeStatus.full_tradingagents_graph.env_flag;

  return (
    <div className="settings-section-grid">
      {/* Research Runner */}
      <ResearchSystemStatus/>
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Runner control</span>
            <h3>Research Runner</h3>
          </div>
          <StatusPill tone={runnerMode === "tradingagents-graph-runner" ? "positive" : "paper"}>
            {runnerMode === "tradingagents-graph-runner" ? "Full graph" : "Safe synthesis"}
          </StatusPill>
        </header>
        <p className="settings-panel-copy">
          Choose between the lightweight safe-synthesis runner and the full TradingAgents
          multi-agent graph. {formatFullGraphStatus(runtimeStatus).toLowerCase()};
          {fullGraphConfigured
            ? " enabled in settings."
            : fullGraphEnv
            ? " TRADEMASTER_ENABLE_REAL_RUNS=1 in environment."
            : " safe synthesis selected."}
        </p>
        <div className="settings-runner-modes">
          <button
            className={runnerModeIs(runtimeStatus, "llm-ui-runner") ? "settings-mode-btn active" : "settings-mode-btn"}
            disabled={savingRunnerMode}
            onClick={() => void handleResearchRunnerModeChange("llm-ui-runner")}
            type="button"
            aria-pressed={runnerModeIs(runtimeStatus, "llm-ui-runner")}
          >
            <strong>Safe synthesis</strong>
            <span>llm-ui-runner · single-pass LLM synthesis</span>
          </button>
          <button
            className={
              runnerModeIs(runtimeStatus, "tradingagents-graph-runner")
                ? "settings-mode-btn active"
                : "settings-mode-btn"
            }
            disabled={savingRunnerMode}
            onClick={() => void handleResearchRunnerModeChange("tradingagents-graph-runner")}
            type="button"
            aria-pressed={runnerModeIs(runtimeStatus, "tradingagents-graph-runner")}
          >
            <strong>Full TradingAgents graph</strong>
            <span>tradingagents-graph-runner · multi-agent debate</span>
          </button>
        </div>
      </article>

      {/* Research LLM */}
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Research LLM</span>
            <h3>{researchProvider?.name ?? researchLLM.provider_id ?? "—"}</h3>
          </div>
          <StatusPill tone={llmTone(researchLLM)}>
            {llmStatusLabel(researchLLM)}
          </StatusPill>
        </header>
        <dl className="settings-detail-list">
          <SettingsDetail label="Provider ID">
            <code>{researchLLM.provider_id ?? "—"}</code>
          </SettingsDetail>
          <SettingsDetail label="Model">
            <code>{formatStringConfig(researchLLM.model) || formatStringConfig(researchProvider?.config.model) || "—"}</code>
          </SettingsDetail>
          <SettingsDetail label="Base URL">
            <code>{formatStringConfig(researchLLM.base_url) || formatStringConfig(researchProvider?.config.base_url) || "—"}</code>
          </SettingsDetail>
          <SettingsDetail label="Secret ref" tooltip="Resolves to OS keychain / env var at runtime">
            <span>{researchLLM.secret_ref_configured ? "reference set; checked at use" : researchProvider?.config.auth_required === false || String(researchProvider?.config.provider).includes("oauth") ? "provider-managed authentication" : "not set"}</span>
          </SettingsDetail>
          <SettingsDetail label="Fallback expected">
            <span>{researchLLM.fallback_expected ? "Yes" : "No"}</span>
          </SettingsDetail>
        </dl>
      </article>

      {/* Broker */}
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Broker</span>
            <h3>{brokerProvider?.name ?? broker.provider_id ?? "—"}</h3>
          </div>
          <StatusPill tone={broker.paper_only ? "paper" : broker.enabled ? "positive" : "neutral"}>
            {broker.paper_only ? "Paper only" : broker.enabled ? "Enabled; execution unverified" : "Disabled"}
          </StatusPill>
        </header>
        <dl className="settings-detail-list">
          <SettingsDetail label="Provider ID">
            <code>{broker.provider_id ?? "—"}</code>
          </SettingsDetail>
          <SettingsDetail label="Status">
            <span>{broker.status ?? "unknown"}</span>
          </SettingsDetail>
          <SettingsDetail
            label="Approval required"
            tooltip="If true, trades route through the approval ledger before submission"
          >
            <span>{broker.approval_required ? "Yes" : "No"}</span>
          </SettingsDetail>
          <SettingsDetail label="Write authority">
            <span>{brokerProvider ? formatCapability(brokerProvider.write_authority) : "—"}</span>
          </SettingsDetail>
        </dl>
      </article>

      {/* Execution Policy */}
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Execution policy</span>
            <h3>Risk envelope</h3>
          </div>
          <StatusPill tone={policy.paper_mode_required ? "paper" : "positive"}>
            {policy.paper_mode_required ? "Paper enforced" : "Unlocked"}
          </StatusPill>
        </header>
        <dl className="settings-detail-list settings-detail-grid">
          <SettingsDetail label="Max position" tooltip="Per-symbol exposure ceiling as % of portfolio">
            <strong className="settings-numeric">{formatPercent(policy.max_position_percent)}</strong>
          </SettingsDetail>
          <SettingsDetail label="Max sector" tooltip="Aggregate sector exposure cap">
            <strong className="settings-numeric">{formatPercent(policy.max_sector_percent)}</strong>
          </SettingsDetail>
          <SettingsDetail label="Daily turnover" tooltip="Limit on portfolio churn within a session">
            <strong className="settings-numeric">{formatPercent(policy.max_daily_turnover_percent)}</strong>
          </SettingsDetail>
          <SettingsDetail label="Max drawdown" tooltip="Halt threshold for cumulative loss">
            <strong className="settings-numeric">{formatPercent(policy.max_drawdown_percent)}</strong>
          </SettingsDetail>
        </dl>
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Providers sub-section
// ---------------------------------------------------------------------------

function ProvidersSection({
  strategyProtocols,
  loading,
  sortedProviders,
  sortedRoleAssignments,
  providerById,
  runtimeStatus,
  savingProviderId,
  savingRoleKey,
  draftSecretRefs,
  setDraftSecretRefs,
  handleProviderToggle,
  handleSecretRefSave,
  handleProviderHealthCheck,
  handleDeleteUserProvider,
  handleRoleAssignmentChange,
  newProviderDraft,
  setNewProviderDraft,
  creatingProvider,
  handleCreateUserProvider,
  researchProvider,
  availableModels,
  roleModelsDraft,
  setRoleModelsDraft,
  fallbackModel,
  savingRoleModels,
  handleSaveRoleModels
}: {
  loading: boolean;
  strategyProtocols: string[];
  sortedProviders: ProviderConfig[];
  sortedRoleAssignments: ProviderRoleAssignment[];
  providerById: Record<string, ProviderConfig>;
  runtimeStatus: RuntimeStatus | null;
  savingProviderId: string | null;
  savingRoleKey: ProviderRoleKey | null;
  draftSecretRefs: Record<string, string>;
  setDraftSecretRefs: (next: Record<string, string> | ((cur: Record<string, string>) => Record<string, string>)) => void;
  handleProviderToggle: (provider: ProviderConfig, enabled: boolean) => void;
  handleSecretRefSave: (provider: ProviderConfig) => void;
  handleProviderHealthCheck: (provider: ProviderConfig) => void;
  handleDeleteUserProvider: (provider: ProviderConfig) => void;
  handleRoleAssignmentChange: (roleKey: ProviderRoleKey, providerId: string) => void;
  newProviderDraft: {
    name: string;
    kind: UserProviderKind;
    baseUrl: string;
    model: string;
    apiKeyEnv: string;
  };
  setNewProviderDraft: (
    next:
      | { name: string; kind: UserProviderKind; baseUrl: string; model: string; apiKeyEnv: string }
      | ((cur: { name: string; kind: UserProviderKind; baseUrl: string; model: string; apiKeyEnv: string }) => {
          name: string;
          kind: UserProviderKind;
          baseUrl: string;
          model: string;
          apiKeyEnv: string;
        })
  ) => void;
  creatingProvider: boolean;
  handleCreateUserProvider: () => void;
  researchProvider: ProviderConfig | undefined;
  availableModels: ProviderModelList | null;
  roleModelsDraft: {
    providerId: string | null;
    coordinator: string;
    agent: string;
    overrides: Record<string, string>;
  };
  setRoleModelsDraft: (
    next:
      | { providerId: string | null; coordinator: string; agent: string; overrides: Record<string, string> }
      | ((cur: {
          providerId: string | null;
          coordinator: string;
          agent: string;
          overrides: Record<string, string>;
        }) => {
          providerId: string | null;
          coordinator: string;
          agent: string;
          overrides: Record<string, string>;
        })
  ) => void;
  fallbackModel: string;
  savingRoleModels: boolean;
  handleSaveRoleModels: () => void;
}) {
  if (loading && sortedProviders.length === 0) {
    return <LoadingPanel label="Loading provider catalog" />;
  }

  if (sortedProviders.length === 0) {
    return <EmptyPanel label="No providers" detail="Backend returned an empty provider catalog." />;
  }

  return (
    <div className="settings-section-stack">
      {/* Role assignments */}
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Provider role routing</span>
            <h3>Role assignments</h3>
          </div>
          <span className="settings-panel-counter">{sortedRoleAssignments.length}</span>
        </header>
        <p className="settings-panel-copy">
          Each agent role binds to one provider. Switching here updates the active
          backend immediately.
        </p>
        <div className="settings-role-grid">
          {sortedRoleAssignments.map((assignment) => {
            const selectedProvider = providerById[assignment.provider_id];
            const boundedRole = ["research_designer", "research_extractor"].includes(assignment.role_key);
            const supportsRole = (p: ProviderConfig) => !boundedRole || strategyProtocols.includes(String(p.config.provider || "openai").toLowerCase());
            const devModeOn = runtimeStatus?.developer_mode_enabled ?? false;
            const eligibleProviders = providersForRole(assignment.role_key, sortedProviders).filter(
              (provider) =>
                devModeOn || !isDeveloperModeProvider(provider) || provider.provider_id === assignment.provider_id
            );
            return (
              <div className="settings-role-row" key={assignment.role_key}>
                <div className="settings-role-meta">
                  <strong>{ROLE_ASSIGNMENT_LABELS[assignment.role_key]}</strong>
                  <span className="settings-role-surface">{SURFACE_LABELS[assignment.surface]}</span>
                </div>
                <select
                  aria-label={`${ROLE_ASSIGNMENT_LABELS[assignment.role_key]} provider`}
                  disabled={savingRoleKey === assignment.role_key}
                  onChange={(event) =>
                    handleRoleAssignmentChange(assignment.role_key, event.target.value)
                  }
                  value={assignment.provider_id}
                  className="settings-select"
                >
                  {selectedProvider ? null : (
                    <option value={assignment.provider_id}>{assignment.provider_id}</option>
                  )}
                  {eligibleProviders.map((provider) => (
                    <option key={provider.provider_id} value={provider.provider_id} disabled={!supportsRole(provider)}>
                      {provider.name}{!supportsRole(provider) ? " — unsupported for this role" : !provider.enabled ? " — disabled" : ""}
                    </option>
                  ))}
                </select>
                <small className="settings-role-hint">
                  {selectedProvider && !supportsRole(selectedProvider) ? "Blocked: this provider has no verified strategy research adapter. Select Codex or a supported API provider." : selectedProvider && !selectedProvider.enabled ? "This provider is disabled. Enable it and verify its credential before use." : boundedRole && selectedProvider?.config.provider === "codex-oauth" ? "Uses Codex App Server and ChatGPT subscription allowance. Login, model, and the reviewed subscription policy are checked at dispatch." : boundedRole ? "Used for bounded strategy research calls. A model and usable credential are checked at dispatch." : selectedProvider?.primary_use ?? "Provider not in registry"}
                </small>
              </div>
            );
          })}
        </div>
      </article>

      {/* Per-agent model overrides (research provider) */}
      {researchProvider ? (
        <article className="settings-panel">
          <header className="settings-panel-header">
            <div>
              <span className="settings-panel-kicker">Per-agent models</span>
              <h3>{researchProvider.name}</h3>
            </div>
            <span className="settings-panel-counter">
              {availableModels?.source === "unavailable"
                ? "models unavailable"
                : availableModels?.models.length
                ? `${availableModels.models.length} from ${formatModelSource(availableModels.source)}`
                : "loading…"}
            </span>
          </header>
          <div className="settings-model-tiers">
            <div className="settings-model-tier">
              <div>
                <strong>Coordinator default</strong>
                <span>Research Manager · Trader · Portfolio Manager</span>
              </div>
              {renderModelSelect({
                ariaLabel: "Coordinator-tier default model",
                value: roleModelsDraft.coordinator,
                options: availableModels?.models ?? [],
                placeholder: fallbackModel,
                allowClear: false,
                onChange: (value) =>
                  setRoleModelsDraft((current) => ({ ...current, coordinator: value }))
              })}
            </div>
            <div className="settings-model-tier">
              <div>
                <strong>Agent default</strong>
                <span>Applied to every other role unless overridden below</span>
              </div>
              {renderModelSelect({
                ariaLabel: "Agent-tier default model",
                value: roleModelsDraft.agent,
                options: availableModels?.models ?? [],
                placeholder: fallbackModel,
                allowClear: false,
                onChange: (value) =>
                  setRoleModelsDraft((current) => ({ ...current, agent: value }))
              })}
            </div>
          </div>
          <div className="settings-model-overrides">
            {ALL_AGENT_ROLES.map((role) => {
              const isCoordinator = COORDINATOR_AGENT_ROLES.has(role);
              const override = roleModelsDraft.overrides[role] ?? "";
              const resolved = resolveRoleModel(
                role,
                {
                  coordinator: roleModelsDraft.coordinator,
                  agent: roleModelsDraft.agent,
                  overrides: roleModelsDraft.overrides
                },
                fallbackModel
              );
              return (
                <div className="settings-model-override-row" key={role}>
                  <div className="settings-model-override-meta">
                    <strong>{AGENT_ROLE_LABELS[role as AgentRoleKey]}</strong>
                    <span>{isCoordinator ? "Coordinator" : "Agent"}</span>
                  </div>
                  {renderModelSelect({
                    ariaLabel: `${AGENT_ROLE_LABELS[role as AgentRoleKey]} model override`,
                    value: override,
                    options: availableModels?.models ?? [],
                    placeholder: "(use tier default)",
                    allowClear: true,
                    onChange: (value) =>
                      setRoleModelsDraft((current) => ({
                        ...current,
                        overrides: { ...current.overrides, [role]: value }
                      }))
                  })}
                  <small className="settings-resolved">
                    resolves to <code>{resolved || "—"}</code>
                  </small>
                </div>
              );
            })}
          </div>
          <div className="settings-panel-footer">
            <span className="settings-panel-footer-hint">
              {availableModels?.source === "unavailable"
                ? "Model list unavailable — typing is allowed."
                : "Click Save to push overrides to provider config."}
            </span>
            <button
              className="settings-primary-button"
              disabled={savingRoleModels}
              onClick={() => void handleSaveRoleModels()}
              type="button"
            >
              {savingRoleModels ? "Saving…" : "Save per-agent models"}
            </button>
          </div>
        </article>
      ) : null}

      {/* Provider catalog grouped by role */}
      {PROVIDER_GROUPS.map((group) => {
        const providersInGroup = sortedProviders.filter((provider) => provider.role === group.id);
        if (providersInGroup.length === 0) return null;
        return (
          <article className="settings-panel" key={group.id}>
            <header className="settings-panel-header">
              <div>
                <span className="settings-panel-kicker">{group.kicker}</span>
                <h3>{group.label}</h3>
              </div>
              <span className="settings-panel-counter">{providersInGroup.length}</span>
            </header>
            <div className="settings-provider-rows">
              {providersInGroup.map((provider) => (
                <ProviderRow
                  key={provider.provider_id}
                  provider={provider}
                  draftSecretRef={draftSecretRefs[provider.provider_id] ?? ""}
                  saving={savingProviderId === provider.provider_id}
                  onSecretChange={(value) =>
                    setDraftSecretRefs((current) => ({ ...current, [provider.provider_id]: value }))
                  }
                  onSecretSave={() => handleSecretRefSave(provider)}
                  onToggle={() => handleProviderToggle(provider, !provider.enabled)}
                  onHealthCheck={() => handleProviderHealthCheck(provider)}
                  onDelete={
                    isUserDefinedProvider(provider) ? () => handleDeleteUserProvider(provider) : undefined
                  }
                />
              ))}
            </div>
          </article>
        );
      })}

      {/* Add custom provider */}
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Custom endpoint</span>
            <h3>Add custom provider</h3>
          </div>
          <StatusPill tone="neutral">New</StatusPill>
        </header>
        <p className="settings-panel-copy">
          Point at any OpenAI-compatible or Anthropic-compatible endpoint. Useful for
          GLM, Kimi, custom OpenRouter proxies, or a local gateway.
        </p>
        <div className="settings-form-grid">
          <label className="settings-field">
            <span>Name</span>
            <input
              aria-label="Custom provider name"
              value={newProviderDraft.name}
              onChange={(event) =>
                setNewProviderDraft((current) => ({ ...current, name: event.target.value }))
              }
              placeholder="GLM"
              className="settings-input"
            />
          </label>
          <label className="settings-field">
            <span>Kind</span>
            <select
              aria-label="Custom provider kind"
              value={newProviderDraft.kind}
              onChange={(event) =>
                setNewProviderDraft((current) => ({
                  ...current,
                  kind: event.target.value as UserProviderKind
                }))
              }
              className="settings-select"
            >
              <option value="openai-compatible">OpenAI-compatible</option>
              <option value="anthropic-compatible">Anthropic-compatible</option>
            </select>
          </label>
          <label className="settings-field settings-field-wide">
            <span>Base URL</span>
            <input
              aria-label="Custom provider base URL"
              value={newProviderDraft.baseUrl}
              onChange={(event) =>
                setNewProviderDraft((current) => ({ ...current, baseUrl: event.target.value }))
              }
              placeholder="https://api.z.ai/api/paas/v4/"
              className="settings-input"
            />
          </label>
          <label className="settings-field">
            <span>Default model</span>
            <input
              aria-label="Custom provider default model"
              value={newProviderDraft.model}
              onChange={(event) =>
                setNewProviderDraft((current) => ({ ...current, model: event.target.value }))
              }
              placeholder="glm-4.6"
              className="settings-input"
            />
          </label>
          <label className="settings-field">
            <span>API key ref</span>
            <input
              aria-label="Custom provider API key reference"
              value={newProviderDraft.apiKeyEnv}
              onChange={(event) =>
                setNewProviderDraft((current) => ({ ...current, apiKeyEnv: event.target.value }))
              }
              placeholder="env:ZHIPU_API_KEY"
              className="settings-input"
            />
          </label>
        </div>
        <div className="settings-panel-footer">
          <span className="settings-panel-footer-hint">Enable and assign to a role after adding.</span>
          <button
            className="settings-primary-button"
            disabled={
              creatingProvider ||
              !newProviderDraft.name.trim() ||
              !newProviderDraft.baseUrl.trim() ||
              !newProviderDraft.model.trim()
            }
            onClick={() => void handleCreateUserProvider()}
            type="button"
          >
            {creatingProvider ? "Adding…" : "Add provider"}
          </button>
        </div>
      </article>
    </div>
  );
}

function ProviderRow({
  provider,
  draftSecretRef,
  saving,
  onSecretChange,
  onSecretSave,
  onToggle,
  onHealthCheck,
  onDelete
}: {
  provider: ProviderConfig;
  draftSecretRef: string;
  saving: boolean;
  onSecretChange: (value: string) => void;
  onSecretSave: () => void;
  onToggle: () => void;
  onHealthCheck: () => void;
  onDelete?: () => void;
}) {
  const statusTone = computeProviderTone(provider);
  const statusLabel = computeProviderStatusLabel(provider);
  return (
    <div className="settings-provider-row">
      <div className="settings-provider-head">
        <button
          type="button"
          role="switch"
          aria-checked={provider.enabled}
          className={provider.enabled ? "settings-toggle on" : "settings-toggle"}
          disabled={saving}
          onClick={onToggle}
          aria-label={`${provider.enabled ? "Disable" : "Enable"} ${provider.name}`}
        >
          <span className="settings-toggle-knob" />
        </button>
        <div className="settings-provider-identity">
          <strong>{provider.name}</strong>
          <code className="settings-provider-id">{provider.provider_id}</code>
        </div>
        <div className="settings-provider-tags">
          {isDeveloperModeProvider(provider) ? <span className="settings-tag">Developer mode</span> : null}
          {isUserDefinedProvider(provider) ? <span className="settings-tag">User-defined</span> : null}
          {provider.config.graph_runner_supported === false ? (
            <span className="settings-tag warn">Unsupported for full graph</span>
          ) : null}
        </div>
        <StatusPill tone={statusTone}>{statusLabel}</StatusPill>
      </div>
      <div className="settings-provider-body">
        <p className="settings-provider-use">{provider.primary_use}</p>
        <div className="settings-provider-secret">
          <label htmlFor={`${provider.provider_id}-secret`}>Secret ref</label>
          <input
            id={`${provider.provider_id}-secret`}
            value={draftSecretRef}
            onChange={(event) => onSecretChange(event.target.value)}
            placeholder="keychain:provider:account or env:NAME"
            className="settings-input"
            disabled={saving}
          />
          <button
            type="button"
            className="settings-mini-button"
            disabled={saving}
            aria-label={`Save credential reference for ${provider.name}`}
            onClick={onSecretSave}
          >
            Save
          </button>
        </div>
        <div className="settings-provider-actions">
          <span className="settings-provider-health">{formatHealth(provider.health)}</span>
          <button
            type="button"
            className="settings-mini-button"
            disabled={saving}
            onClick={onHealthCheck}
            aria-label={`Check credential for ${provider.name}`}
            title="Checks local credential availability only; does not contact the provider or verify model access"
          >
            Check credential
          </button>
          {onDelete ? (
            <button
              type="button"
              className="settings-mini-button danger"
              disabled={saving}
              onClick={onDelete}
            >
              Delete
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Backups sub-section
// ---------------------------------------------------------------------------

function BackupsSection({
  historyAvailable,
  loading,
  snapshot,
  snapshotList,
  snapshotPending,
  backupKeyRef,
  setBackupKeyRef,
  backupKeyConfigured,
  verifyingSnapshotId,
  snapshotVerification,
  handleCreateSnapshot,
  handleCreateEncryptedSnapshot,
  handleVerifySnapshot,
  setSnapshot,
  setSnapshotVerification
}: {
  historyAvailable: boolean;
  loading: boolean;
  snapshot: SnapshotManifestRecord | null;
  snapshotList: SnapshotManifestRecord[];
  snapshotPending: boolean;
  backupKeyRef: string;
  setBackupKeyRef: (value: string) => void;
  backupKeyConfigured: boolean;
  verifyingSnapshotId: string | null;
  snapshotVerification: SnapshotVerification | null;
  handleCreateSnapshot: () => void;
  handleCreateEncryptedSnapshot: () => void;
  handleVerifySnapshot: (record?: SnapshotManifestRecord) => void;
  setSnapshot: (next: SnapshotManifestRecord | null) => void;
  setSnapshotVerification: (next: SnapshotVerification | null) => void;
}) {
  return (
    <div className="settings-section-stack">
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Snapshot creation</span>
            <h3>Create encrypted backup</h3>
          </div>
          <StatusPill tone="neutral">
            {backupKeyConfigured ? "Key reference entered; unchecked" : "Key reference missing"}
          </StatusPill>
        </header>
        {!backupKeyConfigured ? (
          <div className="settings-callout warn">
            Set <code>TRADEMASTER_BACKUP_KEY</code> to enable encrypted backups. Manifest-only
            manifests still work without it; they contain no restorable data.
          </div>
        ) : null}
        <label className="settings-field">
          <span>Key reference</span>
          <input
            aria-label="Backup key secret reference"
            value={backupKeyRef}
            onChange={(event) => setBackupKeyRef(event.target.value)}
            className="settings-input"
            placeholder="env:TRADEMASTER_BACKUP_KEY"
          />
        </label>
        <div className="settings-panel-footer">
          <span className="settings-panel-footer-hint">
            Manifests record hashes only and cannot restore data. New encrypted backups contain the database and research artifacts. Credentials and the backup key must be kept separately. Older backups retain their original scope. The key reference is resolved when you create or verify a backup.
          </span>
          <div className="settings-button-row">
            <button
              type="button"
              className="settings-secondary-button"
              disabled={snapshotPending}
              onClick={() => void handleCreateSnapshot()}
            >
              {snapshotPending ? "Working…" : "Manifest only"}
            </button>
            <button
              type="button"
              className="settings-primary-button"
              disabled={snapshotPending || !backupKeyConfigured}
              onClick={() => void handleCreateEncryptedSnapshot()}
            >
              {snapshotPending ? "Working…" : "Encrypt & store"}
            </button>
          </div>
        </div>
      </article>

      {snapshot ? (
        <article className="settings-panel">
          <header className="settings-panel-header">
            <div>
              <span className="settings-panel-kicker">Focused snapshot</span>
              <h3>{snapshot.snapshot_id}</h3>
            </div>
            <StatusPill tone={snapshot.manifest.backup_artifact ? "positive" : "neutral"}>
              {snapshot.manifest.backup_artifact ? "Encrypted backup" : "Manifest only — no backup file"}
            </StatusPill>
          </header>
          <dl className="settings-detail-list settings-detail-grid">
            <SettingsDetail label="Created">
              <span>{new Date(snapshot.created_at).toLocaleString()}</span>
            </SettingsDetail>
            <SettingsDetail label="Files">
              <strong className="settings-numeric">{snapshot.manifest.files.filter((f) => f.path !== snapshot.manifest.backup_artifact?.path).length}</strong>
            </SettingsDetail>
            <SettingsDetail label="Total bytes">
              <strong className="settings-numeric">{formatBytes(totalBytes(snapshot))}</strong>
            </SettingsDetail>
            <SettingsDetail label="Storage profile">
              <span>{snapshot.storage_profile}</span>
            </SettingsDetail>
          </dl>
          {snapshot.manifest.backup_artifact ? (
            <>
              <SettingsDetail label="Artifact path" full>
                <code className="settings-mono-block">{snapshot.manifest.backup_artifact.path}</code>
              </SettingsDetail>
              <SettingsDetail label="SHA-256" full>
                <code className="settings-mono-block">{snapshot.manifest.backup_artifact.sha256}</code>
              </SettingsDetail>
            </>
          ) : null}
          {snapshotVerification ? (
            <div
              className={
                snapshotVerification.valid
                  ? "settings-callout positive"
                  : "settings-callout negative"
              }
            >
              <strong>
                {snapshotVerification.valid ? "Verification passed" : "Verification failed"}
              </strong>
              <span>
                {snapshotVerification.files?.filter((file) => file.verified).length ?? 0} verified
              </span>
            </div>
          ) : null}
          <div className="settings-panel-footer">
            <span className="settings-panel-footer-hint">
              {snapshot.manifest.backup_artifact ? "Verification decrypts the backup and checks its archived file hashes. It does not restore your workspace." : "This record contains hashes only. There is no backup file to verify or restore."}
            </span>
            {snapshot.manifest.backup_artifact ? (
              <button
                type="button"
                className="settings-secondary-button"
                disabled={snapshotPending || !backupKeyConfigured}
                onClick={() => void handleVerifySnapshot()}
              >
                {snapshotPending ? "Working…" : "Verify backup integrity"}
              </button>
            ) : null}
          </div>
        </article>
      ) : null}

      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">History</span>
            <h3>Snapshots</h3>
          </div>
          <span className="settings-panel-counter">{historyAvailable ? snapshotList.length : "—"}</span>
        </header>
        {loading && snapshotList.length === 0 ? (
          <LoadingPanel label="Loading snapshots" compact />
        ) : !historyAvailable ? (
          <EmptyPanel label="Snapshot history unavailable" detail="Reload Settings to retry. No backup count can be confirmed." compact />
        ) : snapshotList.length === 0 ? (
          <EmptyPanel label="No snapshots yet" detail="Create one above to start the chain." compact />
        ) : (
          <ul className="snapshot-history-list settings-snapshot-history">
            {snapshotList.map((record) => {
              const isEncrypted = Boolean(record.manifest.backup_artifact);
              const isFocused = snapshot?.snapshot_id === record.snapshot_id;
              return (
                <li
                  key={record.snapshot_id}
                  className={isFocused ? "settings-snapshot-item focused" : "settings-snapshot-item"}
                >
                  <div className="settings-snapshot-meta">
                    <strong>{record.snapshot_id}</strong>
                    <span>
                      {new Date(record.created_at).toLocaleString()} ·{" "}
                      {record.manifest.files.filter((f) => f.path !== record.manifest.backup_artifact?.path).length} files · {formatBytes(totalBytes(record))}
                    </span>
                  </div>
                  <div className="settings-snapshot-tags">
                    <StatusPill tone={isEncrypted ? "positive" : "neutral"}>
                      {isEncrypted ? "Encrypted backup" : "Manifest only"}
                    </StatusPill>
                  </div>
                  <div className="settings-snapshot-actions">
                    <button
                      type="button"
                      className="settings-mini-button"
                      disabled={snapshotPending}
                      onClick={() => {
                        setSnapshot(record);
                        setSnapshotVerification(null);
                      }}
                    >
                      Focus
                    </button>
                    {isEncrypted ? (
                      <button
                        type="button"
                        className="settings-mini-button"
                        disabled={snapshotPending || !backupKeyConfigured}
                        onClick={() => void handleVerifySnapshot(record)}
                      >
                        {verifyingSnapshotId === record.snapshot_id ? "Verifying…" : "Verify"}
                      </button>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Developer sub-section
// ---------------------------------------------------------------------------

function DeveloperSection({
  runtimeStatus,
  savingDeveloperMode,
  handleDeveloperModeToggle,
  handleExportSettings,
  providerCount,
  snapshotCount,
  researchRoleAssignment
}: {
  runtimeStatus: RuntimeStatus | null;
  savingDeveloperMode: boolean;
  handleDeveloperModeToggle: (next: boolean) => void;
  handleExportSettings: () => void;
  providerCount: number;
  snapshotCount: number;
  researchRoleAssignment: ProviderRoleAssignment | undefined;
}) {
  const devModeOn = runtimeStatus?.developer_mode_enabled ?? false;
  const apiBase = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8797";
  const nextDevUrl = typeof window !== "undefined" ? window.location.origin : "http://127.0.0.1:3000";

  return (
    <div className="settings-section-grid">
      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Developer mode</span>
            <h3>{devModeOn ? "On" : "Off"}</h3>
          </div>
          <StatusPill tone={devModeOn ? "positive" : "neutral"}>
            {devModeOn ? "Experimental enabled" : "Locked"}
          </StatusPill>
        </header>
        <p className="settings-panel-copy">
          Exposes experimental providers (e.g. the Codex CLI OAuth bridge) for role
          assignment. Off by default.
        </p>
        <div className="settings-panel-footer">
          <span className="settings-panel-footer-hint">
            Toggling does not restart the runtime; assignments take effect on next request.
          </span>
          <button
            type="button"
            className={devModeOn ? "settings-mode-btn active" : "settings-mode-btn"}
            disabled={savingDeveloperMode}
            onClick={() => void handleDeveloperModeToggle(!devModeOn)}
            aria-pressed={devModeOn}
          >
            <strong>{devModeOn ? "Disable" : "Enable"}</strong>
            <span>{devModeOn ? "hide experimental providers" : "show experimental providers"}</span>
          </button>
        </div>
      </article>

      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Runtime info</span>
            <h3>Endpoints</h3>
          </div>
        </header>
        <dl className="settings-detail-list">
          <SettingsDetail label="API base">
            <code>{apiBase}</code>
          </SettingsDetail>
          <SettingsDetail label="Web dev URL">
            <code>{nextDevUrl}</code>
          </SettingsDetail>
          <SettingsDetail label="Research runner">
            <span>{runtimeStatus?.research_runner.mode ?? "—"}</span>
          </SettingsDetail>
          <SettingsDetail label="Research role">
            <code>{researchRoleAssignment?.provider_id ?? "—"}</code>
          </SettingsDetail>
          <SettingsDetail label="Providers loaded">
            <strong className="settings-numeric">{providerCount}</strong>
          </SettingsDetail>
          <SettingsDetail label="Snapshots tracked">
            <strong className="settings-numeric">{snapshotCount}</strong>
          </SettingsDetail>
        </dl>
      </article>

      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Export</span>
            <h3>Settings JSON</h3>
          </div>
        </header>
        <p className="settings-panel-copy">
          Download a JSON blob of the current runtime + provider catalog + role
          assignments. Useful for backup or migration to another machine.
        </p>
        <div className="settings-panel-footer">
          <span className="settings-panel-footer-hint">
            Exports provider settings and credential references. Keep a separate copy of the referenced credentials; this file cannot authenticate providers on another machine.
          </span>
          <button type="button" className="settings-primary-button" onClick={handleExportSettings}>
            Download JSON
          </button>
        </div>
      </article>

      <article className="settings-panel">
        <header className="settings-panel-header">
          <div>
            <span className="settings-panel-kicker">Local state</span>
            <h3>Reset caches</h3>
          </div>
        </header>
        <p className="settings-panel-copy">
          Forces the workspace to refetch every catalog from the API. Useful after editing
          providers via the CLI or after restarting the backend.
        </p>
        <div className="settings-panel-footer">
          <span className="settings-panel-footer-hint">
            Hard reload also clears the Next.js client-side query cache.
          </span>
          <button
            type="button"
            className="settings-secondary-button"
            onClick={() => {
              if (typeof window !== "undefined") {
                window.location.reload();
              }
            }}
          >
            Hard reload
          </button>
        </div>
      </article>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared subcomponents
// ---------------------------------------------------------------------------

function StatusPill({
  children,
  tone
}: {
  children: ReactNode;
  tone: "positive" | "paper" | "negative" | "neutral";
}) {
  return <span className={`settings-pill tone-${tone}`}>{children}</span>;
}

function SettingsDetail({
  children,
  label,
  tooltip,
  full
}: {
  children: ReactNode;
  label: string;
  tooltip?: string;
  full?: boolean;
}) {
  return (
    <div className={full ? "settings-detail full" : "settings-detail"}>
      <dt className="settings-detail-label" title={tooltip}>
        {label}
      </dt>
      <dd className="settings-detail-value">{children}</dd>
    </div>
  );
}

function LoadingPanel({ label, compact }: { label: string; compact?: boolean }) {
  return (
    <div className={compact ? "settings-empty compact" : "settings-empty"}>
      <strong>{label}</strong>
      <span>fetching from API…</span>
    </div>
  );
}

function EmptyPanel({ detail, label, compact }: { detail: string; label: string; compact?: boolean }) {
  return (
    <div className={compact ? "settings-empty compact" : "settings-empty"}>
      <strong>{label}</strong>
      <span>{detail}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Pure helpers
// ---------------------------------------------------------------------------

function formatFullGraphStatus(status: RuntimeStatus | null): string {
  if (!status) return "loading";
  return status.full_tradingagents_graph.enabled ? "Enabled" : "Safe mode";
}

function runnerModeIs(
  status: RuntimeStatus | null,
  mode: "llm-ui-runner" | "tradingagents-graph-runner"
): boolean {
  return (status?.research_runner.configured_mode ?? status?.research_runner.mode) === mode;
}

function compareProviders(left: ProviderConfig, right: ProviderConfig): number {
  const surfacePriority = ["agent-data", "human-cockpit", "ai-harness", "platform"];
  const leftSurface = surfacePriority.indexOf(left.control_surface);
  const rightSurface = surfacePriority.indexOf(right.control_surface);
  if (leftSurface !== rightSurface) return leftSurface - rightSurface;

  if (left.status !== right.status) {
    return left.status === "available" ? -1 : 1;
  }

  return left.name.localeCompare(right.name);
}

function providersForRole(roleKey: ProviderRoleKey, providers: ProviderConfig[]): ProviderConfig[] {
  const requiredRole: Record<ProviderRoleKey, ProviderRole> = {
    broker: "brokerage",
    execution_llm: "llm",
    market_data: "market-data",
    observability: "observability",
    portfolio: "portfolio",
    research_llm: "llm",
    research_designer: "llm",
    research_extractor: "llm",
    safety: "safety"
  };

  return providers.filter((provider) => provider.role === requiredRole[roleKey]);
}

function isDeveloperModeProvider(provider: ProviderConfig): boolean {
  return provider.config.developer_mode === true;
}

function isUserDefinedProvider(provider: ProviderConfig): boolean {
  return provider.config.user_defined === true;
}

function formatModelSource(source: ProviderModelList["source"]): string {
  switch (source) {
    case "codex_cache":
      return "Codex CLI cache";
    case "api":
      return "provider /v1/models";
    case "static":
      return "built-in list";
    default:
      return "no source";
  }
}

function renderModelSelect({
  ariaLabel,
  value,
  options,
  placeholder,
  allowClear,
  onChange
}: {
  ariaLabel: string;
  value: string;
  options: string[];
  placeholder: string;
  allowClear: boolean;
  onChange: (value: string) => void;
}) {
  if (options.length === 0) {
    return (
      <input
        aria-label={ariaLabel}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        className="settings-input"
      />
    );
  }
  const includesCurrent = value === "" || options.includes(value);
  return (
    <select
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
      className="settings-select"
    >
      {allowClear ? <option value="">{placeholder}</option> : null}
      {!includesCurrent ? <option value={value}>{value} (custom)</option> : null}
      {options.map((option) => (
        <option key={option} value={option}>
          {option}
        </option>
      ))}
    </select>
  );
}

function formatCapability(capability: string): string {
  return capability.replaceAll("-", " ");
}

function formatHealth(health: Record<string, unknown>): string {
  const secret = health.secret;
  if (isSecretHealth(secret)) {
    const when = typeof health.checked_at === "string" ? ` · checked ${new Date(health.checked_at).toLocaleString()}` : "";
    return `${secret.backend === "none" ? "No API key required" : `${secret.backend} credential ${secret.available ? "available" : "missing"}`}${when} · connection untested`;
  }
  const status = health.status;
  return typeof status === "string" ? status.replaceAll("_", " ") : "not checked";
}

function isSecretHealth(value: unknown): value is { available: boolean; backend: string } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.backend === "string" && typeof candidate.available === "boolean";
}

function computeProviderTone(provider: ProviderConfig): "positive" | "paper" | "negative" | "neutral" {
  if (!provider.enabled) return "neutral";
  const status = provider.status;
  if (status === "available") return "positive";
  if (status === "needs_key") return "paper";
  if (status === "planned") return "neutral";
  return "negative";
}

function computeProviderStatusLabel(provider: ProviderConfig): string {
  if (!provider.enabled) return "Disabled";
  switch (provider.status) {
    case "available":
      return "Enabled";
    case "needs_key":
      return "Needs key";
    case "planned":
      return "Planned";
    case "disabled":
      return "Disabled";
    default:
      return provider.status;
  }
}

function llmTone(researchLLM: RuntimeStatus["research_llm"]): "positive" | "paper" | "negative" | "neutral" {
  if (!researchLLM.enabled) return "neutral";
  if (researchLLM.status === "available") return "positive";
  return "neutral";
}

function llmStatusLabel(researchLLM: RuntimeStatus["research_llm"]): string {
  if (!researchLLM.enabled) return "Disabled";
  if (researchLLM.status === "available") return "Enabled; call unverified";
  return researchLLM.status ?? "Unknown";
}

function formatStringConfig(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function formatPercent(value: number | undefined): string {
  if (value === undefined || value === null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function totalBytes(record: SnapshotManifestRecord): number {
  const artifact = record.manifest.backup_artifact?.size_bytes ?? 0;
  if (artifact > 0) return artifact;
  return record.manifest.files.reduce((sum, file) => sum + (file.size_bytes ?? 0), 0);
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  return `${value.toFixed(value >= 10 ? 0 : 1)} ${units[unitIndex]}`;
}
