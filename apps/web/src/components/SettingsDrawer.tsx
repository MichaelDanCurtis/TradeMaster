"use client";

import { getMarketProviderCatalog, type MarketProviderDescriptor } from "@/lib/market-data";

const ROLE_LABELS: Record<MarketProviderDescriptor["roles"][number], string> = {
  brokerage: "Brokerage",
  "market-data": "Market data",
  portfolio: "Portfolio"
};

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const providers = Object.values(getMarketProviderCatalog()).sort(compareProviders);

  if (!open) {
    return null;
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
            <span>Provider catalog</span>
            <strong>{providers.length}</strong>
          </div>
          <div className="settings-provider-list">
            {providers.map((provider) => (
              <article className="settings-provider" key={provider.id}>
                <div className="settings-provider-heading">
                  <div>
                    <strong>{provider.name}</strong>
                    <span>{provider.primaryUse}</span>
                  </div>
                  <span className={`provider-status ${provider.status}`}>{provider.status}</span>
                </div>
                <div className="settings-role-row">
                  {provider.roles.map((role) => (
                    <span key={role}>{ROLE_LABELS[role]}</span>
                  ))}
                </div>
                <div className="provider-capabilities">
                  {provider.capabilities.slice(0, 5).map((capability) => (
                    <span key={capability}>{formatCapability(capability)}</span>
                  ))}
                </div>
              </article>
            ))}
          </div>
        </section>
      </aside>
    </div>
  );
}

function compareProviders(left: MarketProviderDescriptor, right: MarketProviderDescriptor): number {
  if (left.status !== right.status) {
    return left.status === "available" ? -1 : 1;
  }

  return left.name.localeCompare(right.name);
}

function formatCapability(capability: string): string {
  return capability.replaceAll("-", " ");
}
