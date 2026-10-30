"use client";

import { useEffect, useRef, useState } from "react";

import { ActiveProgramsTable } from "@/components/ActiveProgramsTable";
import {
  AlgorithmCatalogueRail,
  SIMPLE_MODE_ALGORITHMS
} from "@/components/AlgorithmCatalogueRail";
import { AlgorithmWorkbench } from "@/components/AlgorithmWorkbench";
import { PendingIntentsLadder } from "@/components/PendingIntentsLadder";

/**
 * A research→execution handoff payload. Produced by MarketShell when the user
 * approves an idea (SymbolDetailDrawer Buy/Sell, Morning Scan approve) and
 * consumed exactly once here: the side control is set, the Simple Mode
 * "Market buy/sell" algorithm is selected, and `onConsumePendingIntent`
 * clears the shell-level state so it never re-applies.
 */
export type PendingQuantIntent = {
  symbol: string;
  side: "buy" | "sell";
};

type Props = {
  symbol: string;
  /** Non-null when an approved idea is waiting to be pre-filled. */
  pendingIntent?: PendingQuantIntent | null;
  /** Called once after the intent has been applied to the workbench. */
  onConsumePendingIntent?: () => void;
};

/**
 * Composer for the Quant tab — the 4-quadrant workbench described in the
 * audit:
 *
 *   A · CATALOGUE (left rail, ~320px)
 *   B · WORKBENCH (center)
 *   C · ACTIVE PROGRAMS (full-width table)
 *   D · APPROVAL LADDER (full-width stack of pending intents)
 *
 * Owns the `algo` selection state and threads it from the catalogue rail
 * into the center workbench. The other parallel agent mounts this from
 * `QuantWorkspace.tsx`.
 */
export function QuantWorkbench({ symbol, pendingIntent, onConsumePendingIntent }: Props) {
  // Default-select the first Simple Mode algorithm so the workbench is
  // populated on first render. The user's spec asks for "market" but the
  // backend registry has no `market` algo; SIMPLE_MODE_ALGORITHMS[0] is
  // `sniper`, labeled "Market buy/sell" in the rail.
  const [algo, setAlgo] = useState<string | null>(
    SIMPLE_MODE_ALGORITHMS[0]?.name ?? null
  );

  // Side handoff into AlgorithmWorkbench. The token makes each applied
  // intent distinct so the workbench can re-apply even when two consecutive
  // approvals carry the same side (e.g. Buy NVDA, then Buy AAPL).
  const [sideIntent, setSideIntent] = useState<{ side: "buy" | "sell"; token: number } | null>(null);

  // One-line "the handoff happened" confirmation, e.g.
  // "Loaded from research: NVDA · BUY". Dismissible and auto-fades.
  const [prefillNotice, setPrefillNotice] = useState<PendingQuantIntent | null>(null);

  // Apply each pending intent exactly once. Identity-keyed: MarketShell
  // creates a fresh object per approval, and we record the last applied
  // reference so re-renders (or the post-consume null → re-set cycle)
  // never double-apply.
  const lastAppliedIntentRef = useRef<PendingQuantIntent | null>(null);
  const intentTokenRef = useRef(0);
  useEffect(() => {
    if (!pendingIntent) return;
    if (lastAppliedIntentRef.current === pendingIntent) return;
    lastAppliedIntentRef.current = pendingIntent;

    // Land the user on a ready ticket: Simple Mode "Market buy/sell"
    // (backend name `sniper`) with the approved side pre-set.
    setAlgo(SIMPLE_MODE_ALGORITHMS[0]?.name ?? null);
    intentTokenRef.current += 1;
    setSideIntent({ side: pendingIntent.side, token: intentTokenRef.current });
    setPrefillNotice(pendingIntent);
    onConsumePendingIntent?.();
  }, [pendingIntent, onConsumePendingIntent]);

  // Auto-fade the confirmation after 8s. The dismiss button clears it sooner.
  useEffect(() => {
    if (!prefillNotice) return;
    const id = window.setTimeout(() => setPrefillNotice(null), 8000);
    return () => window.clearTimeout(id);
  }, [prefillNotice]);

  return (
    <section className="quant-workbench" aria-label="Quant execution workbench">
      <header className="quant-workbench-header">
        <span className="panel-kicker">Quant · execution workbench</span>
        <h1>Deterministic algorithms</h1>
        <p className="quant-workbench-tagline">
          {symbol} · trading agents running quant algorithms. Everything is deterministic.
        </p>
      </header>

      {/* Prefill confirmation — passive status line; never takes focus. */}
      {prefillNotice ? (
        <p
          role="status"
          className="quant-prefill-notice"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.5rem",
            margin: "0 0 0.75rem",
            padding: "0.4rem 0.75rem",
            borderLeft: "3px solid var(--accent-blue)",
            background: "rgba(41, 98, 255, 0.08)",
            fontSize: "0.8rem"
          }}
        >
          <span>
            Loaded from research:{" "}
            <span style={{ fontFamily: "var(--font-mono)", fontWeight: 600 }}>
              {prefillNotice.symbol.toUpperCase()} · {prefillNotice.side.toUpperCase()}
            </span>
          </span>
          <button
            type="button"
            onClick={() => setPrefillNotice(null)}
            aria-label="Dismiss prefill confirmation"
            style={{
              marginLeft: "auto",
              background: "none",
              border: "none",
              color: "inherit",
              cursor: "pointer",
              fontSize: "0.9rem",
              lineHeight: 1,
              padding: "0 0.25rem",
              opacity: 0.7
            }}
          >
            ×
          </button>
        </p>
      ) : null}

      <div className="quant-workbench-grid">
        <AlgorithmCatalogueRail selectedAlgorithm={algo} onSelect={setAlgo} />
        <AlgorithmWorkbench algorithm={algo} symbol={symbol} sideIntent={sideIntent} />
      </div>

      <ActiveProgramsTable />
      <PendingIntentsLadder />
    </section>
  );
}
