"use client";

/**
 * VerdictChip — compact "the agents read this symbol" overlay used on the
 * Book → Positions cards. Shows the latest completed run's action as a
 * BUY/HOLD/SELL-tinted pill, the run's confidence (mono %) when it carried
 * one, and the age of the read ("2h"). The thesis travels in the title
 * tooltip. Non-interactive unless an onClick is provided (later: open the
 * underlying run).
 */

import type { ScanVerdict } from "@/lib/types";

export type VerdictActionKind = "buy" | "sell" | "hold";

const SELL_WORDS = ["sell", "underweight", "trim", "reduce", "exit", "short"];
const BUY_WORDS = ["buy", "overweight", "accumulate", "add", "long"];

/** Classify a verdict's action (falling back to rating) into buy/sell/hold. */
export function verdictActionKind(
  action: string | null,
  rating: string | null = null
): VerdictActionKind {
  const text = (action ?? rating ?? "").toLowerCase();
  if (SELL_WORDS.some((word) => text.includes(word))) return "sell";
  if (BUY_WORDS.some((word) => text.includes(word))) return "buy";
  return "hold";
}

/** "12m" / "3h" / "2d" since the run completed. Null when unparseable. */
function formatAge(iso: string): string | null {
  // Backend timestamps may arrive timezone-naive (UTC); pin them to Z.
  const normalized = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso) ? iso : `${iso}Z`;
  const ts = Date.parse(normalized);
  if (Number.isNaN(ts)) return null;
  const minutes = Math.max(0, Math.floor((Date.now() - ts) / 60_000));
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.floor(hours / 24)}d`;
}

function formatConfidence(confidence: number | null): string | null {
  if (confidence === null || !Number.isFinite(confidence)) return null;
  // Graph runs report 0..1; tolerate already-percent payloads defensively.
  const pct = confidence <= 1 ? confidence * 100 : confidence;
  return `${Math.round(pct)}%`;
}

export function VerdictChip({
  verdict,
  onClick
}: {
  verdict: ScanVerdict;
  /** Optional — when provided the chip becomes a button (e.g. open the run). */
  onClick?: () => void;
}) {
  const kind = verdictActionKind(verdict.action, verdict.rating);
  const label = verdict.action ?? verdict.rating ?? kind;
  const confidence = formatConfidence(verdict.confidence);
  const age = formatAge(verdict.run_created_at);

  const headline = [verdict.rating, verdict.action].filter(Boolean).join(" · ");
  const tooltipParts = [headline, verdict.thesis ?? ""].filter(Boolean);
  const tooltip = tooltipParts.length > 0 ? tooltipParts.join("\n") : undefined;
  const ariaLabel = `Agent verdict for ${verdict.symbol}: ${label}`;

  const body = (
    <>
      <span className={`verdict-chip-action verdict-chip-action-${kind}`}>{label}</span>
      {confidence !== null ? <span className="verdict-chip-confidence">{confidence}</span> : null}
      {age !== null ? <span className="verdict-chip-age">{age}</span> : null}
    </>
  );

  if (onClick) {
    return (
      <button
        aria-label={ariaLabel}
        className="verdict-chip"
        onClick={onClick}
        title={tooltip}
        type="button"
      >
        {body}
      </button>
    );
  }

  return (
    <span aria-label={ariaLabel} className="verdict-chip" title={tooltip}>
      {body}
    </span>
  );
}
