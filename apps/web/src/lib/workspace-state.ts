import type { TerminalNotification, WorkspaceId } from "./workspace-data.ts";

export type WorkspaceShellState = {
  activeWorkspace: WorkspaceId;
  selectedSymbol: string;
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

export function dismissNotification(
  notifications: TerminalNotification[],
  notificationId: string
): TerminalNotification[] {
  return notifications.filter((notification) => notification.id !== notificationId);
}

export function visibleNotifications(
  state: WorkspaceShellState,
  notifications: TerminalNotification[]
): TerminalNotification[] {
  // Settings is an admin/configuration surface — suppress symbol-context toasts
  // while the operator is configuring providers, secrets, snapshots.
  return state.activeWorkspace === "settings" ? [] : notifications;
}
