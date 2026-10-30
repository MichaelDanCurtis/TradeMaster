"use client";

import { useEffect, useRef } from "react";
import type { TerminalNotification } from "@/lib/workspace-data";

function Toast({ notification, onDismiss }: { notification: TerminalNotification; onDismiss: (id: string) => void }) {
  const dismiss = useRef(onDismiss);
  useEffect(() => { dismiss.current = onDismiss; }, [onDismiss]);
  useEffect(() => {
    if (!notification.ttl) return;
    const timer = window.setTimeout(() => dismiss.current(notification.id), notification.ttl);
    return () => window.clearTimeout(timer);
  }, [notification.id, notification.ttl]);
  return (
    <article className={`toast-item ${notification.severity}`}>
      <div><span>{formatWorkspace(notification.linkedWorkspace)}</span><strong>{notification.title}</strong><p>{notification.body}</p></div>
      <button aria-label={`Dismiss ${notification.title}`} onClick={() => onDismiss(notification.id)} type="button">x</button>
    </article>
  );
}

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
        <Toast key={notification.id} notification={notification} onDismiss={onDismiss} />
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
