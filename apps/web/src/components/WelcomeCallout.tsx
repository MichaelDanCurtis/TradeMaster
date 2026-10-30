"use client";

import { useEffect, useState } from "react";

import { listOpenTrades, listRuns } from "@/lib/api";
import type { WatchlistItem } from "@/lib/types";

const DISMISS_KEY = "tm.onboarding.welcome-dismissed";
const DEFAULT_WATCHLIST_LENGTH = 4;

/**
 * First-run welcome callout. Visible at the top of the Portfolio tab when
 * all three are true:
 *   - watchlist is still at the default 4 symbols
 *   - no runs have ever been created
 *   - no open trades
 *
 * Dismissal persists in localStorage under `tm.onboarding.welcome-dismissed`.
 */
export function WelcomeCallout({ watchlistItems }: { watchlistItems: WatchlistItem[] }) {
  const [shouldShow, setShouldShow] = useState(false);

  useEffect(() => {
    let cancelled = false;

    // Bail immediately if the user already dismissed this in a prior session.
    try {
      if (window.localStorage.getItem(DISMISS_KEY) === "1") {
        return;
      }
    } catch {
      // Storage disabled (private mode / quota); fall through and probe.
    }

    // Watchlist heuristic: if the user has added or removed any default
    // symbol, they're past first-run.
    if (watchlistItems.length !== DEFAULT_WATCHLIST_LENGTH) {
      return;
    }

    async function probe() {
      try {
        const [runs, trades] = await Promise.all([
          listRuns({ limit: 1 }),
          listOpenTrades({ limit: 1 })
        ]);
        if (cancelled) return;
        if (runs.length === 0 && (trades.items ?? []).length === 0) {
          setShouldShow(true);
        }
      } catch {
        // Backend not reachable yet — that itself is a first-run signal, so
        // we still show the callout. Better an extra hello than silence.
        if (!cancelled) setShouldShow(true);
      }
    }

    void probe();
    return () => {
      cancelled = true;
    };
  }, [watchlistItems.length]);

  function dismiss() {
    try {
      window.localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // Storage disabled; the callout will reappear next session.
    }
    setShouldShow(false);
  }

  if (!shouldShow) return null;

  return (
    <aside className="welcome-callout" role="note" aria-label="Welcome to TradeMaster">
      <div className="welcome-callout-body">
        <strong className="welcome-callout-title">Welcome.</strong>
        <p className="welcome-callout-text">
          TradeMaster is paper-trading against Alpaca only — no real money is moved.
          Try: open Research, pick a ticker, hit <strong>Run committee</strong>.
        </p>
      </div>
      <button
        type="button"
        className="secondary-button compact welcome-callout-dismiss"
        onClick={dismiss}
        aria-label="Dismiss welcome message"
      >
        Dismiss
      </button>
    </aside>
  );
}
