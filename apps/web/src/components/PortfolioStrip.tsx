"use client";

/**
 * Persistent portfolio strip — equity / day P&L / exposure / market session.
 *
 * Lives above every workspace except Settings (see MarketShell.tsx). Data is
 * live from the Alpaca paper broker via the backend portfolio-data endpoints:
 *   - equity:    listPortfolioAccounts → accounts[0].current_balance
 *   - day P&L:   sum(holding.value - holding.cost_basis) across holdings
 *   - exposure:  sum(holding.value) / equity, capped at 100%
 *
 * Session badge (PRE-OPEN / OPEN / CLOSING / AFTER-HOURS / CLOSED) is computed
 * locally from the user's wall clock projected to America/New_York and ticks
 * every 30 seconds.
 *
 * Degradation rules:
 *   - loading: show "..." in mono in each value slot, never 0
 *   - no Alpaca creds (403/404): show "Link Alpaca" pill in equity, "—" elsewhere
 *   - API error: same as no-creds, but pill reads "Alpaca offline"
 *
 * No goals. No rules-slack pills. Both moved out of global chrome — goals
 * don't fit a quant trading app; rules slack belongs inside Quant.
 */

import { useEffect, useMemo, useState } from "react";

import { listPortfolioAccounts, listPortfolioHoldings } from "@/lib/api";
import type { PortfolioAccount, PortfolioHolding } from "@/lib/types";

// ────────────────────────────────────────────────────────────────────────────
// Formatters
// ────────────────────────────────────────────────────────────────────────────

const fmtMoney = (n: number) =>
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0
  });

const fmtSigned = (n: number) =>
  (n >= 0 ? "+" : "") +
  n.toLocaleString("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 0
  });

const fmtPercent = (n: number) => `${n >= 0 ? "+" : ""}${n.toFixed(2)}%`;

// ────────────────────────────────────────────────────────────────────────────
// Portfolio data state
// ────────────────────────────────────────────────────────────────────────────

type PortfolioState =
  | { phase: "loading" }
  | {
      phase: "live";
      equity: number;
      dayPnl: number;
      dayPnlPct: number;
      exposurePct: number;
    }
  | { phase: "fallback"; reason: "no-creds" | "api-error" };

function computeDerived(
  account: PortfolioAccount | undefined,
  holdings: PortfolioHolding[]
): {
  equity: number;
  dayPnl: number;
  dayPnlPct: number;
  exposurePct: number;
} {
  const equity = account?.current_balance ?? 0;

  // Day P&L proxy: sum(value − cost_basis) across positions.
  // Alpaca's /v2/positions returns market_value and cost_basis on each row;
  // the broker bridge maps those to value/cost_basis here.
  const dayPnl = holdings.reduce((acc, h) => {
    if (h.value === null || h.cost_basis === null) return acc;
    return acc + (h.value - h.cost_basis);
  }, 0);

  // dayPnlPct = dayPnl / (equity − dayPnl) × 100, i.e. against opening equity.
  const opening = equity - dayPnl;
  const dayPnlPct = opening > 0 ? (dayPnl / opening) * 100 : 0;

  // Exposure: sum of holding values / equity, capped at 100.
  const exposureSum = holdings.reduce((acc, h) => acc + (h.value ?? 0), 0);
  const exposurePct =
    equity > 0 ? Math.min(100, Math.max(0, (exposureSum / equity) * 100)) : 0;

  return { equity, dayPnl, dayPnlPct, exposurePct };
}

// ────────────────────────────────────────────────────────────────────────────
// Market session
// ────────────────────────────────────────────────────────────────────────────

type SessionKind = "pre-open" | "open" | "closing" | "after-hours" | "closed";

type SessionInfo = {
  kind: SessionKind;
  label: string;
  tooltip: string;
};

/**
 * Project `now` into America/New_York and return the current trading session.
 *
 * Boundaries (regular trading day, ignoring market holidays):
 *   pre-open    04:00 – 09:30
 *   open        09:30 – 15:55
 *   closing     15:55 – 16:00
 *   after-hours 16:00 – 20:00
 *   closed      otherwise (weekends + overnight)
 */
function deriveSession(now: Date): SessionInfo {
  // Build ET parts via Intl — robust across DST shifts.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/New_York",
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false
  }).formatToParts(now);

  const lookup = (type: string): string =>
    parts.find((p) => p.type === type)?.value ?? "";

  const weekday = lookup("weekday"); // "Mon" … "Sun"
  const hourStr = lookup("hour");
  const minuteStr = lookup("minute");

  // Intl gives "24" at midnight in some locales; normalise to 0.
  const hour = hourStr === "24" ? 0 : Number(hourStr) || 0;
  const minute = Number(minuteStr) || 0;
  const minutes = hour * 60 + minute;

  const isWeekend = weekday === "Sat" || weekday === "Sun";

  if (isWeekend) {
    return {
      kind: "closed",
      label: "CLOSED",
      tooltip: "Market: closed · weekend"
    };
  }

  if (minutes >= 4 * 60 && minutes < 9 * 60 + 30) {
    return {
      kind: "pre-open",
      label: "PRE-OPEN",
      tooltip: "Market: pre-open · opens 9:30 AM ET"
    };
  }
  if (minutes >= 9 * 60 + 30 && minutes < 15 * 60 + 55) {
    return {
      kind: "open",
      label: "OPEN",
      tooltip: "Market: open · closes 4:00 PM ET"
    };
  }
  if (minutes >= 15 * 60 + 55 && minutes < 16 * 60) {
    return {
      kind: "closing",
      label: "CLOSING",
      tooltip: "Market: closing in <5 min · 4:00 PM ET"
    };
  }
  if (minutes >= 16 * 60 && minutes < 20 * 60) {
    return {
      kind: "after-hours",
      label: "AFTER-HOURS",
      tooltip: "Market: after-hours · ends 8:00 PM ET"
    };
  }

  return {
    kind: "closed",
    label: "CLOSED",
    tooltip: "Market: closed · opens 4:00 AM ET (pre-open)"
  };
}

// ────────────────────────────────────────────────────────────────────────────
// Component
// ────────────────────────────────────────────────────────────────────────────

export function PortfolioStrip() {
  const [portfolio, setPortfolio] = useState<PortfolioState>({
    phase: "loading"
  });
  const [now, setNow] = useState<Date|null>(null);

  // Fetch equity + holdings once on mount. We don't poll the broker — the
  // strip stays static between page interactions; if the user wants fresh
  // numbers they'll navigate to Brief or refresh.
  useEffect(() => {
    let isCurrent = true;
    setPortfolio({ phase: "loading" });

    Promise.all([
      listPortfolioAccounts("alpaca-paper-broker"),
      listPortfolioHoldings("alpaca-paper-broker")
    ])
      .then(([accountsCatalog, holdingsCatalog]) => {
        if (!isCurrent) return;
        const account = accountsCatalog.accounts[0];
        if (!account) {
          setPortfolio({ phase: "fallback", reason: "no-creds" });
          return;
        }
        const derived = computeDerived(account, holdingsCatalog.holdings);
        setPortfolio({ phase: "live", ...derived });
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        const reason: "no-creds" | "api-error" =
          caught.status === 403 || caught.status === 404
            ? "no-creds"
            : "api-error";
        setPortfolio({ phase: "fallback", reason });
      });

    return () => {
      isCurrent = false;
    };
  }, []);

  // Tick the session clock every 30 seconds so the badge transitions across
  // 9:30 / 15:55 / 16:00 / 20:00 without a page reload.
  useEffect(() => {
    setNow(new Date());
    const interval = window.setInterval(() => {
      setNow(new Date());
    }, 30_000);
    return () => {
      window.clearInterval(interval);
    };
  }, []);

  const session = useMemo(() => now?deriveSession(now):null, [now]);

  const exposureBar = useMemo(() => {
    if (portfolio.phase !== "live") return { width: "0%" };
    const pct = Math.min(100, Math.max(0, portfolio.exposurePct));
    return { width: `${pct}%` };
  }, [portfolio]);

  // Render helpers — keep slot widths stable across phases so the strip
  // doesn't reflow when data lands.
  const renderEquity = () => {
    if (portfolio.phase === "loading") {
      return (
        <strong className="portfolio-strip-value-mono portfolio-strip-value-pending">
          …
        </strong>
      );
    }
    if (portfolio.phase === "fallback") {
      return (
        <span
          className="portfolio-strip-link-pill"
          title={
            portfolio.reason === "no-creds"
              ? "Enable Alpaca in Settings → Providers and set the alpaca-paper-broker credential."
              : "Alpaca portfolio endpoint is unreachable. Backend may be offline."
          }
        >
          {portfolio.reason === "no-creds" ? "Link Alpaca" : "Alpaca offline"}
        </span>
      );
    }
    return (
      <strong className="portfolio-strip-value-mono">
        {fmtMoney(portfolio.equity)}
      </strong>
    );
  };

  const renderDayPnl = () => {
    if (portfolio.phase === "loading") {
      return (
        <strong className="portfolio-strip-value-mono portfolio-strip-value-pending">
          …
        </strong>
      );
    }
    if (portfolio.phase === "fallback") {
      return (
        <strong className="portfolio-strip-value-mono portfolio-strip-value-pending">
          —
        </strong>
      );
    }
    const isPositive = portfolio.dayPnl >= 0;
    return (
      <strong
        className={`portfolio-strip-value-mono ${
          isPositive ? "is-positive" : "is-negative"
        }`}
      >
        {fmtSigned(portfolio.dayPnl)}{" "}
        <span className="portfolio-strip-pct">
          {fmtPercent(portfolio.dayPnlPct)}
        </span>
      </strong>
    );
  };

  const renderExposure = () => {
    if (portfolio.phase === "loading") {
      return (
        <div className="portfolio-strip-exposure-row">
          <strong className="portfolio-strip-value-mono portfolio-strip-value-pending">
            …
          </strong>
        </div>
      );
    }
    if (portfolio.phase === "fallback") {
      return (
        <div className="portfolio-strip-exposure-row">
          <strong className="portfolio-strip-value-mono portfolio-strip-value-pending">
            —
          </strong>
        </div>
      );
    }
    return (
      <div className="portfolio-strip-exposure-row">
        <strong className="portfolio-strip-value-mono">
          {Math.round(portfolio.exposurePct)}%
        </strong>
        <div className="portfolio-strip-exposure-bar" aria-hidden="true">
          <div className="portfolio-strip-exposure-fill" style={exposureBar} />
        </div>
      </div>
    );
  };

  return (
    <section className="portfolio-strip" aria-label="Portfolio posture">
      <div className="portfolio-strip-metric">
        <span className="portfolio-strip-kicker">Equity</span>
        {renderEquity()}
      </div>

      <div className="portfolio-strip-metric">
        <span className="portfolio-strip-kicker">Day P&amp;L</span>
        {renderDayPnl()}
      </div>

      <div className="portfolio-strip-metric portfolio-strip-exposure">
        <span className="portfolio-strip-kicker">Exposure</span>
        {renderExposure()}
      </div>

      <div className="portfolio-strip-metric portfolio-strip-session">
        <span className="portfolio-strip-kicker">Session</span>
        <span
          className={`portfolio-strip-session-badge mode-${session?.kind??"unknown"}`}
          title={session?.tooltip??"Reading local session time"}
        >
          {session?.label??"—"}
        </span>
      </div>
    </section>
  );
}
