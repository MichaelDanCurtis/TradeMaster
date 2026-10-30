"use client";

/**
 * TabNav — flat four-tab primary navigation.
 *
 * Signed off 2026-05-20 as the replacement for the three-substrate model.
 * TradingView / Webull register: uppercase, sans semibold, 14px,
 * accent-blue underline on active.
 *
 * Tabs:
 *   PORTFOLIO  — where you are today
 *   RESEARCH   — what to invest in
 *   QUANT      — deterministic execution
 *   SETTINGS   — configuration
 */

import type { WorkspaceId } from "@/lib/workspace-data";

const TAB_ORDER: WorkspaceId[] = ["portfolio", "research", "quant", "settings"];

const TAB_LABELS: Record<WorkspaceId, string> = {
  portfolio: "PORTFOLIO",
  research: "RESEARCH",
  quant: "QUANT",
  settings: "SETTINGS"
};

const TAB_TAGLINES: Record<WorkspaceId, string> = {
  portfolio: "Where you are today",
  research: "What to invest in",
  quant: "Deterministic execution",
  settings: "Configuration"
};

export function TabNav({
  activeTab,
  onSelectTab
}: {
  activeTab: WorkspaceId;
  onSelectTab: (tab: WorkspaceId) => void;
}) {
  return (
    <nav className="tab-nav" aria-label="TradeMaster primary tabs">
      <div className="tab-nav-row" role="tablist">
        {TAB_ORDER.map((tab) => (
          <button
            aria-current={tab === activeTab ? "page" : undefined}
            aria-selected={tab === activeTab}
            className={tab === activeTab ? "tab-nav-button active" : "tab-nav-button"}
            key={tab}
            onClick={() => onSelectTab(tab)}
            role="tab"
            type="button"
          >
            <span className="tab-nav-label">{TAB_LABELS[tab]}</span>
            <span className="tab-nav-tagline">{TAB_TAGLINES[tab]}</span>
          </button>
        ))}
      </div>
    </nav>
  );
}
