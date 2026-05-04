"use client";

import { useEffect, useMemo, useState } from "react";

import { checkProviderHealth, createSnapshot, listProviderConfigs, updateProviderConfig } from "@/lib/api";
import type { ProviderConfig, ProviderControlSurface, ProviderRole, SnapshotManifestRecord } from "@/lib/types";

const ROLE_LABELS: Record<ProviderRole, string> = {
  brokerage: "Brokerage",
  llm: "LLM",
  "market-data": "Market data",
  observability: "Observability",
  portfolio: "Portfolio"
};

const SURFACE_LABELS: Record<ProviderControlSurface, string> = {
  "agent-data": "Agent data",
  "ai-harness": "AI harness",
  "human-cockpit": "Human cockpit",
  platform: "Platform"
};

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [providers, setProviders] = useState<ProviderConfig[]>([]);
  const [draftSecretRefs, setDraftSecretRefs] = useState<Record<string, string>>({});
  const [snapshot, setSnapshot] = useState<SnapshotManifestRecord | null>(null);
  const [loading, setLoading] = useState(false);
  const [savingProviderId, setSavingProviderId] = useState<string | null>(null);
  const [snapshotPending, setSnapshotPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;

    let cancelled = false;
    setLoading(true);
    listProviderConfigs()
      .then((catalog) => {
        if (cancelled) return;
        setProviders(catalog.providers);
        setDraftSecretRefs(
          Object.fromEntries(catalog.providers.map((provider) => [provider.provider_id, provider.secret_ref ?? ""]))
        );
        setError(null);
      })
      .catch((caught) => {
        if (cancelled) return;
        setError(caught instanceof Error ? caught.message : "Provider config load failed");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [open]);

  const sortedProviders = useMemo(() => [...providers].sort(compareProviders), [providers]);

  if (!open) {
    return null;
  }

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
      const created = await createSnapshot({ encryptionMode: "age", offsiteTarget: "manual-offsite" });
      setSnapshot(created);
      setError(null);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Snapshot creation failed");
    } finally {
      setSnapshotPending(false);
    }
  }

  return (
    <div className="settings-overlay" role="presentation">
      <button className="settings-scrim" aria-label="Close settings" onClick={onClose} type="button" />
      <aside className="settings-drawer" aria-label="Provider and brokerage settings">
        <header className="settings-drawer-header">
          <div>
            <span className="panel-kicker">Utility</span>
            <h2>Settings</h2>
          </div>
          <button className="icon-button" aria-label="Close settings" onClick={onClose} type="button">
            x
          </button>
        </header>
        <section className="settings-section">
          <div className="section-title">
            <span>Provider registry</span>
            <strong>{loading ? "..." : sortedProviders.length}</strong>
          </div>
          {error ? <p className="error">{error}</p> : null}
          <div className="settings-provider-list">
            {sortedProviders.map((provider) => (
              <article className="settings-provider durable-provider" key={provider.provider_id}>
                <div className="settings-provider-heading">
                  <div>
                    <strong>{provider.name}</strong>
                    <span>{provider.primary_use}</span>
                  </div>
                  <span className={`provider-status ${provider.status}`}>{formatStatus(provider.status)}</span>
                </div>
                <div className="settings-role-row">
                  <span>{ROLE_LABELS[provider.role]}</span>
                  <span>{SURFACE_LABELS[provider.control_surface]}</span>
                  <span>{formatCapability(provider.write_authority)}</span>
                  {provider.enabled ? <span>enabled</span> : <span>disabled</span>}
                </div>
                <div className="provider-capabilities">
                  {provider.capabilities.slice(0, 5).map((capability) => (
                    <span key={capability}>{formatCapability(capability)}</span>
                  ))}
                </div>
                <div className="provider-secret-row">
                  <label htmlFor={`${provider.provider_id}-secret-ref`}>Secret ref</label>
                  <input
                    id={`${provider.provider_id}-secret-ref`}
                    onChange={(event) =>
                      setDraftSecretRefs((current) => ({
                        ...current,
                        [provider.provider_id]: event.target.value
                      }))
                    }
                    placeholder="keychain:provider:account"
                    value={draftSecretRefs[provider.provider_id] ?? ""}
                  />
                  <button
                    disabled={savingProviderId === provider.provider_id}
                    onClick={() => void handleSecretRefSave(provider)}
                    type="button"
                  >
                    Save ref
                  </button>
                </div>
                <div className="provider-toggle-row">
                  <button
                    className={provider.enabled ? "secondary-button active" : "secondary-button"}
                    disabled={savingProviderId === provider.provider_id}
                    onClick={() => void handleProviderToggle(provider, !provider.enabled)}
                    type="button"
                  >
                    {provider.enabled ? "Disable provider" : "Enable provider"}
                  </button>
                  <span>{formatHealth(provider.health)}</span>
                  <button
                    disabled={savingProviderId === provider.provider_id}
                    onClick={() => void handleProviderHealthCheck(provider)}
                    type="button"
                  >
                    Check secret
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
        <section className="settings-section snapshot-section">
          <div className="section-title">
            <span>Local backup</span>
            <strong>{snapshot ? "1" : "0"}</strong>
          </div>
          <div className="snapshot-card">
            <div>
              <strong>Encrypted snapshot manifest</strong>
              <span>Records DB path, file hashes, encryption intent, and offsite target. Upload is a later step.</span>
            </div>
            <button disabled={snapshotPending} onClick={() => void handleCreateSnapshot()} type="button">
              {snapshotPending ? "Creating..." : "Create manifest"}
            </button>
          </div>
          {snapshot ? (
            <div className="snapshot-result">
              <span>{snapshot.snapshot_id}</span>
              <strong>{snapshot.encryption_mode}</strong>
              <p>{snapshot.manifest.files[0]?.path}</p>
              <code>{snapshot.manifest.files[0]?.sha256}</code>
            </div>
          ) : null}
        </section>
      </aside>
    </div>
  );
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

function formatCapability(capability: string): string {
  return capability.replaceAll("-", " ");
}

function formatStatus(status: ProviderConfig["status"]): string {
  return status.replace("_", " ");
}

function formatHealth(health: Record<string, unknown>): string {
  const secret = health.secret;
  if (isSecretHealth(secret)) {
    return `${secret.backend} secret ${secret.available ? "available" : "missing"}`;
  }
  const status = health.status;
  return typeof status === "string" ? status.replaceAll("_", " ") : "not checked";
}

function isSecretHealth(value: unknown): value is { available: boolean; backend: string } {
  if (typeof value !== "object" || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate.backend === "string" && typeof candidate.available === "boolean";
}
