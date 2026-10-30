import { useEffect, useRef, useState } from "react";

import { listRunEvents, openRunEventSource } from "@/lib/api";
import type { RunEvent } from "@/lib/types";

const TERMINAL_TYPES = new Set(["run.completed", "run.failed", "run.canceled"]);

export type RunEventStreamStatus =
  | "idle"
  | "connecting"
  | "live"
  | "completed"
  | "error";

export type RunEventStreamState = {
  events: RunEvent[];
  status: RunEventStreamStatus;
  error: string | null;
};

/**
 * Subscribe to the live SSE event stream for a run.
 *
 * Opens an EventSource on mount / whenever `runId` changes, parses each
 * incoming `data:` payload as a {@link RunEvent}, and accumulates events
 * in order. The connection is closed automatically on a terminal event
 * (`run.completed` / `run.failed` / `run.canceled`) or when the component
 * unmounts.
 *
 * Falls back to a one-shot HTTP poll of `/api/runs/{id}/events` if the
 * EventSource fails to connect three times in a row, so consumers still
 * end up with a finished event list even when SSE is unavailable.
 */
export function useRunEventStream(runId: string | null): RunEventStreamState {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [status, setStatus] = useState<RunEventStreamStatus>("idle");
  const [error, setError] = useState<string | null>(null);
  const failureCountRef = useRef(0);

  useEffect(() => {
    setEvents([]);
    setError(null);

    if (!runId) {
      setStatus("idle");
      return;
    }

    setStatus("connecting");
    failureCountRef.current = 0;

    let cancelled = false;
    let source: EventSource | null = null;
    let pollTimer: ReturnType<typeof globalThis.setTimeout> | null = null;

    const fallbackPoll = async () => {
      try {
        const polled = await listRunEvents(runId);
        if (cancelled) return;
        setEvents(polled);
        const last = polled[polled.length - 1];
        if (last && TERMINAL_TYPES.has(last.type)) {
          setStatus("completed");
        } else {
          setStatus("error");
          setError("Live stream unavailable; showing last known events.");
        }
      } catch (caught) {
        if (cancelled) return;
        setStatus("error");
        setError(
          caught instanceof Error ? caught.message : "Failed to fetch run events"
        );
      }
    };

    const connect = () => {
      source = openRunEventSource(runId);

      source.onopen = () => {
        if (cancelled) return;
        failureCountRef.current = 0;
        setStatus((prev) => (prev === "completed" ? prev : "live"));
      };

      source.onmessage = (message) => {
        if (cancelled || !message.data) return;
        try {
          const parsed = JSON.parse(message.data) as RunEvent;
          setEvents((prev) => {
            // De-dupe by sequence in case a reconnect replays the tail.
            if (prev.some((existing) => existing.sequence === parsed.sequence)) {
              return prev;
            }
            return [...prev, parsed];
          });
          if (TERMINAL_TYPES.has(parsed.type)) {
            setStatus("completed");
            source?.close();
            source = null;
          }
        } catch {
          // Ignore malformed payloads — heartbeats are sent as comments
          // (`:keepalive`) and don't fire onmessage at all.
        }
      };

      source.onerror = () => {
        if (cancelled) return;
        source?.close();
        source = null;
        failureCountRef.current += 1;
        if (failureCountRef.current >= 3) {
          void fallbackPoll();
          return;
        }
        setStatus("connecting");
        pollTimer = globalThis.setTimeout(connect, 1000);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (pollTimer !== null) {
        globalThis.clearTimeout(pollTimer);
      }
      source?.close();
      source = null;
    };
  }, [runId]);

  return { events, status, error };
}
