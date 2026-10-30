"use client";

/**
 * WatchStatusStrip — horizontal strip mounted between the TabNav and the
 * PortfolioStrip. One chip per active watcher with a state-coloured dot:
 *
 *   armed    (green)  — enabled, no recent fire, observed value outside band
 *   tight    (amber)  — enabled, observed value within ~2% of threshold
 *   fired    (blue)   — last_fired_at within 5 minutes (pulsing)
 *   disabled (muted)  — enabled=false
 *
 * Auto-refreshes every 15 seconds. Gracefully degrades to an empty state when
 * the backend endpoint is missing (Phase 3 backend may ship after this UI).
 */

import { useEffect, useMemo, useState } from "react";

import { WatcherEndpointMissingError, listWatchers } from "@/lib/api";
import type { WatcherRecord } from "@/lib/types";

const REFRESH_INTERVAL_MS = 15 * 1000;
const FIRED_WINDOW_MS = 5 * 60 * 1000;
const TIGHT_BAND_PCT = 0.02;

type StripPhase =
  | { kind: "loading" }
  | { kind: "ready"; watchers: WatcherRecord[] }
  | { kind: "missing" }
  | { kind: "error"; message: string };

type ChipState = "armed" | "fired" | "tight" | "disabled";

function deriveState(watcher: WatcherRecord, observedValue?: number | null): ChipState {
  if (!watcher.enabled) return "disabled";
  if (watcher.last_fired_at) {
    const firedAt = new Date(watcher.last_fired_at).getTime();
    if (!Number.isNaN(firedAt) && Date.now() - firedAt < FIRED_WINDOW_MS) {
      return "fired";
    }
  }
  // The backend stores a snapshot of the last observed value under
  // payload.last_observed_value when it evaluates a watcher. We honour it if
  // present so the UI can highlight rules that are within striking range.
  const observed =
    observedValue ??
    (typeof watcher.payload?.last_observed_value === "number"
      ? (watcher.payload.last_observed_value as number)
      : null);
  if (observed !== null && watcher.threshold !== 0) {
    const distance = Math.abs(observed - watcher.threshold) / Math.abs(watcher.threshold);
    if (distance <= TIGHT_BAND_PCT) {
      return "tight";
    }
  }
  return "armed";
}

const STATE_RANK: Record<ChipState, number> = {
  fired: 0,
  tight: 1,
  armed: 2,
  disabled: 3
};

function sortWatchers(watchers: WatcherRecord[]): WatcherRecord[] {
  return [...watchers].sort((a, b) => {
    const stateDelta = STATE_RANK[deriveState(a)] - STATE_RANK[deriveState(b)];
    if (stateDelta !== 0) return stateDelta;
    return (b.last_fired_at ?? b.updated_at).localeCompare(a.last_fired_at ?? a.updated_at);
  });
}

export function WatchStatusStrip({
  onSelectSymbol,
  refreshKey
}: {
  onSelectSymbol?: (symbol: string) => void;
  /** Bumping this from a parent forces a re-fetch (e.g. after creating a watcher). */
  refreshKey?: number;
}) {
  const [phase, setPhase] = useState<StripPhase>({ kind: "loading" });
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let isCurrent = true;

    async function load() {
      try {
        const catalog = await listWatchers({ limit: 200 });
        if (!isCurrent) return;
        setPhase({ kind: "ready", watchers: catalog.watchers });
      } catch (caught) {
        if (!isCurrent) return;
        if (caught instanceof WatcherEndpointMissingError) {
          setPhase({ kind: "missing" });
          return;
        }
        setPhase({
          kind: "error",
          message: caught instanceof Error ? caught.message : "Watchers unavailable"
        });
      }
    }

    void load();
    const intervalId = window.setInterval(() => {
      void load();
    }, REFRESH_INTERVAL_MS);

    return () => {
      isCurrent = false;
      window.clearInterval(intervalId);
    };
  }, [refreshKey]);

  const sorted = useMemo(() => {
    if (phase.kind !== "ready") return [];
    return sortWatchers(phase.watchers);
  }, [phase]);

  // Strip stays mounted even when there is nothing to show so the spacing
  // above the TabNav doesn't jump as watchers come and go.
  if (phase.kind === "missing") {
    return (
      <section
        aria-label="Active watchers"
        className="watch-status-strip watch-status-strip-muted"
      >
        <span className="watch-status-strip-kicker">Watchers</span>
        <span className="watch-status-strip-empty">
          Watchers endpoint not available yet — backend is still warming up.
        </span>
      </section>
    );
  }

  if (phase.kind === "loading") {
    return (
      <section aria-label="Active watchers" className="watch-status-strip">
        <span className="watch-status-strip-kicker">Watchers</span>
        <span className="watch-status-strip-empty">loading…</span>
      </section>
    );
  }

  if (phase.kind === "error") {
    return (
      <section aria-label="Active watchers" className="watch-status-strip">
        <span className="watch-status-strip-kicker">Watchers</span>
        <span className="watch-status-strip-empty">{phase.message}</span>
      </section>
    );
  }

  if (sorted.length === 0) {
    return (
      <section aria-label="Active watchers" className="watch-status-strip">
        <span className="watch-status-strip-kicker">Watchers</span>
        <span className="watch-status-strip-empty">
          No active watchers. Add one from any symbol detail.
        </span>
      </section>
    );
  }

  const visible = showAll ? sorted : sorted.slice(0, 8);
  const hiddenCount = sorted.length - visible.length;

  return (
    <section aria-label="Active watchers" className="watch-status-strip">
      <span className="watch-status-strip-kicker">Watchers</span>
      <div className="watch-status-strip-chips" role="list">
        {visible.map((watcher) => {
          const state = deriveState(watcher);
          const symbolUpper = watcher.symbol.toUpperCase();
          const handleClick = () => {
            if (onSelectSymbol && symbolUpper) {
              onSelectSymbol(symbolUpper);
            }
          };
          return (
            <button
              aria-label={`${watcher.name} (${state})`}
              className={`watch-strip-chip watch-strip-chip-${state}`}
              key={watcher.watcher_id}
              onClick={handleClick}
              role="listitem"
              title={`${watcher.name} · ${symbolUpper} · ${state}`}
              type="button"
            >
              <span
                aria-hidden="true"
                className={`watch-strip-dot watch-strip-dot-${state}`}
              />
              <span className="watch-strip-chip-symbol">{symbolUpper}</span>
              <span className="watch-strip-chip-name">{watcher.name}</span>
            </button>
          );
        })}
        {hiddenCount > 0 ? (
          <button
            className="watch-status-strip-more"
            onClick={() => setShowAll(true)}
            type="button"
          >
            show all (+{hiddenCount})
          </button>
        ) : null}
        {showAll && sorted.length > 8 ? (
          <button
            className="watch-status-strip-more"
            onClick={() => setShowAll(false)}
            type="button"
          >
            collapse
          </button>
        ) : null}
      </div>
    </section>
  );
}
