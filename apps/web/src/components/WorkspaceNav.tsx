"use client";

import type { WorkspaceId } from "@/lib/workspace-data";

const WORKSPACES: Array<{ id: WorkspaceId; label: string }> = [
  { id: "agents", label: "Agents" },
  { id: "research", label: "Deep Research" },
  { id: "dashboard", label: "Market Context" },
  { id: "historicals", label: "Historicals" },
  { id: "transactions", label: "Webull Handoff" }
];

export function WorkspaceNav({
  activeWorkspace,
  settingsOpen,
  onSelectWorkspace,
  onToggleSettings
}: {
  activeWorkspace: WorkspaceId;
  settingsOpen: boolean;
  onSelectWorkspace: (workspace: WorkspaceId) => void;
  onToggleSettings: () => void;
}) {
  return (
    <nav className="workspace-nav" aria-label="Workspaces">
      <div className="workspace-tabs" role="tablist" aria-label="Workspace sections">
        {WORKSPACES.map((workspace) => (
          <button
            aria-current={workspace.id === activeWorkspace ? "page" : undefined}
            className={workspace.id === activeWorkspace ? "workspace-tab active" : "workspace-tab"}
            key={workspace.id}
            onClick={() => onSelectWorkspace(workspace.id)}
            type="button"
          >
            {workspace.label}
          </button>
        ))}
      </div>
      <button
        aria-expanded={settingsOpen}
        className={settingsOpen ? "settings-button active" : "settings-button"}
        onClick={onToggleSettings}
        type="button"
      >
        Settings
      </button>
    </nav>
  );
}
