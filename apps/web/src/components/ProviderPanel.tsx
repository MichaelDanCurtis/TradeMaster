"use client";

import { useEffect, useMemo, useState } from "react";

import { listProviders } from "@/lib/api";
import type { ProviderDescriptor, ProviderRole } from "@/lib/types";

const ROLE_LABELS: Record<ProviderRole, string> = {
  brokerage: "Broker",
  llm: "LLM",
  "market-data": "Market",
  observability: "Observability",
  portfolio: "Portfolio",
  safety: "Safety"
};

export function ProviderPanel() {
  const [providers, setProviders] = useState<ProviderDescriptor[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    listProviders()
      .then((catalog) => {
        if (!cancelled) {
          setProviders(catalog.providers);
          setError(null);
        }
      })
      .catch((caught) => {
        if (!cancelled) {
          setError(caught instanceof Error ? caught.message : "Provider load failed");
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const visibleProviders = useMemo(() => {
    const priority = ["available", "needs_key", "planned", "disabled"];
    return [...providers]
      .sort((left, right) => priority.indexOf(left.status) - priority.indexOf(right.status))
      .slice(0, 8);
  }, [providers]);

  return (
    <section className="provider-panel">
      <header className="section-title">
        <span>Providers</span>
        <strong>{providers.length || "..."}</strong>
      </header>
      {error ? <p className="error">{error}</p> : null}
      <div className="provider-list">
        {visibleProviders.map((provider) => (
          <article className="provider-item" key={provider.id}>
            <div>
              <span className="provider-role">{ROLE_LABELS[provider.role]}</span>
              <strong>{provider.name}</strong>
            </div>
            <span className={`provider-status ${provider.status}`}>{formatStatus(provider.status)}</span>
            <div className="provider-capabilities">
              {provider.capabilities.slice(0, 3).map((capability) => (
                <span key={capability}>{formatCapability(capability)}</span>
              ))}
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function formatStatus(status: ProviderDescriptor["status"]): string {
  return status.replace("_", " ");
}

function formatCapability(capability: string): string {
  return capability.replaceAll("-", " ");
}
