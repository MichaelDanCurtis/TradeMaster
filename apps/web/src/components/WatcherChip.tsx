"use client";

/**
 * WatcherChip — per-position chip used by PositionsWorkspace and other lists
 * to surface attached watchers. Compact: shows watcher name + condition +
 * threshold, with a delete affordance. Click to fire-check (manual evaluate).
 *
 * State color is derived from the WatcherRecord:
 *   armed   = enabled and not recently fired → green dot
 *   fired   = last_fired_at within 5 min      → blue pulsing dot
 *   disabled= enabled=false                   → muted gray dot
 */

import { useState } from "react";

import { checkWatcher, deleteWatcher } from "@/lib/api";
import type { WatcherConditionType, WatcherRecord } from "@/lib/types";

const FIRED_WINDOW_MS = 5 * 60 * 1000;

const CONDITION_LABELS: Record<WatcherConditionType, string> = {
  price_above: ">",
  price_below: "<",
  change_pct_above: "Δ% >",
  change_pct_below: "Δ% <",
  volume_above: "vol >"
};

function chipState(watcher: WatcherRecord): "armed" | "fired" | "disabled" {
  if (!watcher.enabled) return "disabled";
  if (watcher.last_fired_at) {
    const firedAt = new Date(watcher.last_fired_at).getTime();
    if (!Number.isNaN(firedAt) && Date.now() - firedAt < FIRED_WINDOW_MS) {
      return "fired";
    }
  }
  return "armed";
}

function fmtThreshold(condition: WatcherConditionType, threshold: number): string {
  if (condition === "change_pct_above" || condition === "change_pct_below") {
    return `${threshold.toFixed(2)}%`;
  }
  if (condition === "volume_above") {
    if (threshold >= 1_000_000) return `${(threshold / 1_000_000).toFixed(1)}M`;
    if (threshold >= 1_000) return `${(threshold / 1_000).toFixed(1)}K`;
    return threshold.toString();
  }
  return `$${threshold.toFixed(2)}`;
}

export function WatcherChip({
  watcher,
  onChange,
  onDelete
}: {
  watcher: WatcherRecord;
  /** Called with the updated watcher after a check; lets the parent re-render. */
  onChange?: (next: WatcherRecord) => void;
  /** Called after delete succeeds. Parent should drop the watcher from its list. */
  onDelete?: (watcherId: string) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const state = chipState(watcher);
  const conditionLabel = CONDITION_LABELS[watcher.condition_type];
  const thresholdLabel = fmtThreshold(watcher.condition_type, watcher.threshold);

  async function handleCheck() {
    setBusy(true);
    setError(null);
    try {
      const result = await checkWatcher(watcher.watcher_id);
      if (result.fire) {
        // Optimistically reflect the fire so the dot turns blue right away.
        onChange?.({
          ...watcher,
          last_fired_at: result.fire.fired_at,
          fire_count: watcher.fire_count + 1
        });
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Check failed");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete(event: React.MouseEvent) {
    event.stopPropagation();
    if (!window.confirm(`Delete watcher "${watcher.name}"?`)) return;
    setBusy(true);
    try {
      await deleteWatcher(watcher.watcher_id);
      onDelete?.(watcher.watcher_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Delete failed");
      setBusy(false);
    }
  }

  return (
    <span
      className={`watcher-chip watcher-chip-${state}${busy ? " is-busy" : ""}`}
      title={error ?? `${watcher.name} · ${watcher.symbol} ${conditionLabel} ${thresholdLabel}`}
    >
      <button
        aria-label={`Check ${watcher.name} now`}
        className="watcher-chip-body"
        disabled={busy}
        onClick={handleCheck}
        type="button"
      >
        <span aria-hidden="true" className={`watcher-chip-dot watcher-chip-dot-${state}`} />
        <span className="watcher-chip-name">{watcher.name}</span>
        <span className="watcher-chip-rule brief-mono">
          {conditionLabel} {thresholdLabel}
        </span>
      </button>
      <button
        aria-label={`Delete watcher ${watcher.name}`}
        className="watcher-chip-delete"
        disabled={busy}
        onClick={handleDelete}
        type="button"
      >
        <span aria-hidden="true">×</span>
      </button>
    </span>
  );
}
