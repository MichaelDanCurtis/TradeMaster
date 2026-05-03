import type { TerminalNotification, WorkspaceId } from "./workspace-data.ts";

export type WorkspaceShellState = {
  activeWorkspace: WorkspaceId;
  selectedSymbol: string;
  settingsOpen: boolean;
};

export function setWorkspace(state: WorkspaceShellState, activeWorkspace: WorkspaceId): WorkspaceShellState {
  return {
    ...state,
    activeWorkspace
  };
}

export function selectSymbol(state: WorkspaceShellState, selectedSymbol: string): WorkspaceShellState {
  return {
    ...state,
    selectedSymbol
  };
}

export function toggleSettings(state: WorkspaceShellState): WorkspaceShellState {
  return {
    ...state,
    settingsOpen: !state.settingsOpen
  };
}

export function dismissNotification(
  notifications: TerminalNotification[],
  notificationId: string
): TerminalNotification[] {
  return notifications.filter((notification) => notification.id !== notificationId);
}
