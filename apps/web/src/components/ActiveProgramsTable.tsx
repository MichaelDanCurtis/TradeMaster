"use client";

import { useEffect, useState } from "react";

import { listExecutionPrograms } from "@/lib/api";
import type { ExecutionProgramRecord } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";

const POLL_INTERVAL_MS = 15_000;

/**
 * Active programs table — full-width row below the workbench.
 *
 * Fetches `GET /api/execution-programs` on mount and polls every 15s.
 * Renders one row per program with symbol, algorithm, side, status,
 * progress bar, filled qty, avg fill, and pause/stop/retry actions.
 *
 * Visual treatment targets a Bloomberg/Webull execution monitor: dense
 * rows, mono numerals, color-coded status, and a live polling heartbeat
 * dot in the header.
 */
export function ActiveProgramsTable() {
  const [programs, setPrograms] = useState<ExecutionProgramRecord[]>([]);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  // `now` ticks once per minute so the "Xh since open" label stays fresh.
  const [lastReadAt, setLastReadAt] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchPrograms() {
      try {
        const catalog = await listExecutionPrograms({ limit: 50 });
        if (cancelled) return;
        setPrograms(catalog.programs ?? []);
        setLoadState("ready");
        setLastReadAt(new Date().toLocaleTimeString());
        setErrorMessage(null);
      } catch (err) {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(err instanceof Error ? err.message : "Programs unavailable");
      }
    }

    void fetchPrograms();
    const interval = window.setInterval(() => {
      void fetchPrograms();
    }, POLL_INTERVAL_MS);

    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, []);

  const runningCount = programs.filter((p) => isRunningState(p.state)).length;

  /**
   * Map a backend `state` string to one of our status tokens used for
   * coloring the status pill and the progress fill.
   */
  function statusToken(state: string): "running" | "paused" | "completed" | "failed" | "canceled" | "pending" {
    const s = state.toLowerCase();
    if (["completed", "filled"].includes(s)) return "completed";
    if (s.includes("fail") || s.includes("error")) return "failed";
    if (s.includes("cancel")) return "canceled";
    if (s.includes("paused")) return "paused";
    if (["submitted", "active", "running", "partially_filled"].includes(s)) return "running";
    return "pending";
  }

  function isRunningState(state: string): boolean {
    return statusToken(state) === "running";
  }

  /**
   * Pull a "side" hint from the program's payload if present. Returns
   * a normalized "buy" | "sell" | null so the side pill renders cleanly.
   */
  function programSide(program: ExecutionProgramRecord): "buy" | "sell" | null {
    const payload = program.payload ?? {};
    if(program.algorithm==="strategy_target"){
      const delta=(payload as {target?:{delta_quantity?:number}}).target?.delta_quantity;
      return typeof delta==="number"&&delta!==0?(delta>0?"buy":"sell"):null;
    }
    const candidate = (payload as { side?: unknown }).side;
    if (typeof candidate !== "string") return null;
    const s = candidate.toLowerCase();
    if (s === "buy" || s === "long") return "buy";
    if (s === "sell" || s === "short") return "sell";
    return null;
  }

  /**
   * Best-effort extraction of filled qty and avg fill price from the
   * payload. These columns gracefully degrade to `—` when absent.
   */
  function programFills(program: ExecutionProgramRecord): { filled: number | null; avg: number | null } {
    const payload = (program.payload ?? {}) as Record<string, unknown>;
    const filled = typeof payload.filled_quantity === "number" ? payload.filled_quantity
      : typeof payload.filled === "number" ? payload.filled
      : null;
    const avg = typeof payload.avg_fill_price === "number" ? payload.avg_fill_price
      : typeof payload.average_price === "number" ? payload.average_price
      : null;
    return { filled, avg };
  }

  const headerMeta = (
    <div className="quant-active-meta">

      <span className="quant-active-meta-count">
        {loadState === "ready" ? runningCount : "—"} <span className="quant-active-meta-dim">recorded active</span>
      </span>
      <span className="quant-active-meta-sep">·</span>
      <span className="quant-active-meta-session">{lastReadAt ? `Records read ${lastReadAt}` : "Not read yet"}</span>
    </div>
  );

  if (loadState === "loading") {
    return (
      <section className="quant-active-table" aria-label="Active programs">
        <header className="quant-active-header">
          <div className="quant-active-header-left">
            <span className="panel-kicker">Active programs</span>
            <h2>Saved execution programs</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-active-status">Loading…</p>
      </section>
    );
  }

  if (loadState === "error") {
    return (
      <section className="quant-active-table" aria-label="Active programs">
        <header className="quant-active-header">
          <div className="quant-active-header-left">
            <span className="panel-kicker">Active programs</span>
            <h2>Saved execution programs</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-active-status error">{errorMessage ?? "Unavailable"}</p>
      </section>
    );
  }

  if (programs.length === 0) {
    return (
      <section className="quant-active-table" aria-label="Active programs">
        <header className="quant-active-header">
          <div className="quant-active-header-left">
            <span className="panel-kicker">Active programs</span>
            <h2>Saved execution programs</h2>
          </div>
          {headerMeta}
        </header>
        <p className="quant-active-status">
          No legacy program records or proposed strategy targets. Review approved TWAP and DCA schedules in the execution scheduler above.
        </p>
      </section>
    );
  }

  return (
    <section className="quant-active-table" aria-label="Active programs">
      <header className="quant-active-header">
        <div className="quant-active-header-left">
          <span className="panel-kicker">Active programs</span>
          <h2>Saved execution programs</h2>
        </div>
        {headerMeta}
      </header>
      <table className="quant-active-rows">
        <thead>
          <tr>
            <th>Symbol</th>
            <th>Algo</th>
            <th>Side</th>
            <th>Status</th>
            <th>Progress</th>
            <th>Filled</th>
            <th>Avg fill</th>
            <th aria-label="Actions"></th>
          </tr>
        </thead>
        <tbody>
          {programs.map((program) => {
            const strategyTarget=program.algorithm==="strategy_target";
            const token = statusToken(program.state);
            const side = programSide(program);
            const { filled, avg } = programFills(program);
            return (
              <tr key={program.program_id} className="quant-active-row quant-active-row-tint">
                <td className="quant-active-symbol">{program.symbol}</td>
                <td>
                  <span className="quant-active-algo">{program.algorithm.replaceAll("_", " ")}</span>
                </td>
                <td>
                  {side ? (
                    <span className={`quant-active-side quant-active-side-${side}`}>{side}</span>
                  ) : (
                    <span className="quant-active-side-empty">—</span>
                  )}
                </td>
                <td>
                  <span className={`quant-active-status-pill quant-active-status-${token}`}>{strategyTarget?"proposed target":program.state.replaceAll("_", " ")}</span>
                </td>
                <td className="quant-active-progress-cell">
                  <span>{strategyTarget ? "See exact order history" : "Not reported"}</span>
                </td>
                <td className={`quant-active-fills ${filled ? "" : "quant-active-num-dim"}`}>
                  {filled != null ? filled.toLocaleString() : "—"}
                </td>
                <td className={`quant-active-avg ${avg ? "" : "quant-active-num-dim"}`}>
                  {avg != null ? `$${avg.toFixed(2)}` : "—"}
                </td>
                <td className="quant-active-actions">
                  {strategyTarget ? <a href="#strategy-deployments">Review deployment</a> : <span title="This legacy program record has no connected scheduler controls">Controls unavailable</span>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </section>
  );
}
