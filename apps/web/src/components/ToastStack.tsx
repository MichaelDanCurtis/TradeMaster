"use client";

import type { TerminalNotification } from "@/lib/workspace-data";

export function ToastStack({
  notifications,
  onDismiss
}: {
  notifications: TerminalNotification[];
  onDismiss: (notificationId: string) => void;
}) {
  if (notifications.length === 0) {
    return null;
  }

  return (
    <section className="toast-stack" aria-label="System notifications" aria-live="polite">
      {notifications.map((notification) => (
        <article className={`toast-item ${notification.severity}`} key={notification.id}>
          <div>
            <span>{formatWorkspace(notification.linkedWorkspace)}</span>
            <strong>{notification.title}</strong>
            <p>{notification.body}</p>
          </div>
          <button aria-label={`Dismiss ${notification.title}`} onClick={() => onDismiss(notification.id)} type="button">
            x
          </button>
        </article>
      ))}
    </section>
  );
}

function formatWorkspace(workspace: TerminalNotification["linkedWorkspace"]): string {
  if (workspace === "research") {
    return "Deep Research";
  }

  return workspace.charAt(0).toUpperCase() + workspace.slice(1);
}
