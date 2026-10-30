"use client";

/**
 * Studio → Providers tab.
 *
 * Provider catalog with role assignments. Initial cut just lists the
 * configured providers + their role assignments + key status. Editing
 * surfaces continue to live in Settings (SettingsDrawer); Providers here
 * is the read-first browse surface so the operator can see at a glance
 * "what's wired, what isn't" without opening the dense settings drawer.
 */

import { useEffect, useState } from "react";

import {
  listProviderConfigs,
  listProviderRoleAssignments,
  getRuntimeStatus
} from "@/lib/api";
import type {
  ProviderConfig,
  ProviderRoleAssignment,
  RuntimeStatus
} from "@/lib/types";

type ProvidersState =
  | { phase: "loading" }
  | {
      phase: "loaded";
      configs: ProviderConfig[];
      assignments: ProviderRoleAssignment[];
      runtime: RuntimeStatus;
    }
  | { phase: "error"; message: string };

export function ProvidersWorkspace() {
  const [state, setState] = useState<ProvidersState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    setState({ phase: "loading" });

    Promise.all([listProviderConfigs(), listProviderRoleAssignments(), getRuntimeStatus()])
      .then(([configsCatalog, assignmentsCatalog, runtime]) => {
        if (!isCurrent) return;
        setState({
          phase: "loaded",
          configs: configsCatalog.providers,
          assignments: assignmentsCatalog.assignments,
          runtime
        });
      })
      .catch((caught: Error) => {
        if (!isCurrent) return;
        setState({
          phase: "error",
          message: caught instanceof Error ? caught.message : "Provider data unavailable"
        });
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  return (
    <section className="providers-workspace" aria-label="Providers">
      <header className="workspace-header providers-header">
        <div>
          <span className="panel-kicker">Studio · Providers</span>
          <h1>What&apos;s wired</h1>
        </div>
      </header>

      {state.phase === "loading" ? <p className="brief-empty">Loading provider catalog…</p> : null}
      {state.phase === "error" ? <p className="brief-empty error">{state.message}</p> : null}

      {state.phase === "loaded" ? (
        <>
          <section className="providers-role-grid">
            {state.assignments.map((a) => {
              const config = state.configs.find((c) => c.provider_id === a.provider_id);
              const enabled = config?.enabled ?? false;
              const secretRef = config?.secret_ref ?? null;
              const statusClass = enabled
                ? secretRef
                  ? "providers-role-card live"
                  : "providers-role-card warn"
                : "providers-role-card off";

              return (
                <article className={statusClass} key={`${a.role_key}-${a.provider_id}`}>
                  <span className="panel-kicker">{a.role_key.replaceAll("_", " ")}</span>
                  <strong>{config?.name ?? a.provider_id}</strong>
                  <small>
                    {enabled ? (secretRef ? "live" : "enabled · no secret") : "disabled"}
                  </small>
                </article>
              );
            })}
          </section>

          <section className="providers-list-section">
            <header className="brief-panel-header">
              <span className="panel-kicker">Full provider catalog</span>
              <span>{state.configs.length} entries</span>
            </header>
            <ul className="providers-full-list">
              {state.configs.map((c) => (
                <li key={c.provider_id} className={c.enabled ? "providers-row enabled" : "providers-row"}>
                  <span className="providers-row-id">
                    <strong>{c.name}</strong>
                    <small>{c.provider_id} · {c.role}</small>
                  </span>
                  <span className="providers-row-status">{c.status}</span>
                  <span className="providers-row-secret">
                    {c.secret_ref ? "secret ✓" : "—"}
                  </span>
                </li>
              ))}
            </ul>
            <p className="brief-empty">
              Edit provider configuration, run health checks, and rotate secrets in <em>Studio → Settings</em>.
            </p>
          </section>
        </>
      ) : null}
    </section>
  );
}
