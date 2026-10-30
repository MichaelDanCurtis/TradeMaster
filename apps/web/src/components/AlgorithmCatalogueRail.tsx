"use client";

import { useEffect, useMemo, useState } from "react";

import { listExecutionAlgorithms } from "@/lib/api";
import type { ExecutionAlgorithmCatalogue } from "@/lib/types";

type LoadState = "loading" | "ready" | "error";
type CatalogueMode = "simple" | "advanced";

type Props = {
  selectedAlgorithm: string | null;
  onSelect: (name: string) => void;
};

/**
 * The Simple Mode curated 6. Home traders need these and nothing else.
 * Each entry maps a friendly label to a backend algorithm `name` from the
 * registry plus a one-line plain-English explainer.
 *
 * NOTE: the backend registry (see tradingagents/algorithms/) does NOT
 * register `market`, `limit`, or `stop_loss` as standalone algorithms.
 * The three substitutions below pick the closest registered match:
 *   - Market buy/sell  → `sniper`         (immediate-or-cancel for full size)
 *   - Limit order      → `adaptive_limit` (limit at the touch + market fallback)
 *   - Stop loss        → `bracket_order`  (market entry + stop-loss + take-profit)
 * `bracket_order` is therefore reused as the stop-loss substitute, so the
 * separate "Bracket order" slot from the spec is replaced with `dca_ladder`,
 * which is the other set-and-forget patient-entry algo on the registry.
 *
 * Exported because the workbench reuses it to render the friendly explainer
 * callout above the parameter form.
 */
export const SIMPLE_MODE_ALGORITHMS: Array<{
  name: string;
  label: string;
  explainer: string;
  /** Unicode glyph rendered in the Simple Mode tile header. Mono-friendly. */
  icon: string;
  /** Two-line tagline shown beneath the label inside the tile. */
  tagline: string;
}> = [
  {
    name: "sniper",
    label: "Triggered IOC",
    explainer:
      "Preview a full-size immediate-or-cancel order at a trigger price. An unfilled remainder is cancelled; this is not a market order.",
    icon: "⚡", // ⚡ — fast
    tagline: "Trigger-price IOC preview."
  },
  {
    name: "adaptive_limit",
    label: "Adaptive limit plan",
    explainer:
      "Preview a limit entry with a later market fallback. The fallback can fill beyond the initial limit; this plan is not scheduled automatically.",
    icon: "⌖", // ⌖ — target
    tagline: "Limit entry with market fallback."
  },
  {
    name: "bracket_order",
    label: "Entry bracket",
    explainer:
      "Preview an entry with a stop and take-profit leg. These legs are analytical until prepared and approved through a supported order ticket.",
    icon: "⛨", // ⛨ — shield
    tagline: "Entry with stop + take-profit attached."
  },
  {
    name: "dca_ladder",
    label: "Dollar-cost rungs",
    explainer:
      "Split your buy across price rungs below the current price. Patient — improves average cost on dips.",
    icon: "≡", // ≡ — ladder rungs
    tagline: "Buys at multiple price levels."
  },
  {
    name: "twap",
    label: "TWAP",
    explainer:
      "Spread your buy across the day instead of all at once. Reduces timing risk.",
    icon: "◷", // ◷ — clock arc
    tagline: "Spread evenly across the day."
  },
  {
    name: "trailing_stop",
    label: "Trailing stop",
    explainer:
      "Preview a stop that follows favorable price moves. This view does not run a trailing-stop scheduler.",
    icon: "➚", // ➚ — climb arrow
    tagline: "Trailing-stop plan preview."
  }
];

/**
 * Plain-English tooltips for technical algorithm terms a first-time home
 * trader is unlikely to recognize. Keyed by backend algorithm `name`.
 * Used by the Advanced Mode catalogue rail as a `title` attribute fallback
 * over the registry's terse description.
 */
const ADVANCED_ALGO_TOOLTIPS: Record<string, string> = {
  vwap:
    "VWAP = volume-weighted average price. Spreads your order across the day in proportion to typical volume.",
  twap:
    "TWAP = time-weighted average price. Spreads your order evenly across the day.",
  bracket_order:
    "Bracket = an entry order with a stop-loss and a take-profit attached. Set-and-forget.",
  sniper:
    "Sniper = immediate-or-cancel full-size order. Takes the offer if it can fill, cancels otherwise.",
  dca_ladder:
    "DCA ladder = dollar-cost averaging. Buys at multiple price levels to average your entry.",
  adaptive_limit:
    "Limit at the touch with a market fallback. Better fills, may not fill at all.",
  trailing_stop:
    "Preview a stop that follows favorable price moves. This view does not run a trailing-stop scheduler.",
  staged_accumulation:
    "Builds a position in stages. Adds size as the trade works, scales back when it doesn't.",
  iceberg:
    "Hides total order size by exposing only a small slice to the market at a time."
};

const CATALOGUE_MODE_STORAGE_KEY = "tm.quant.catalogue-mode";

function readStoredMode(): CatalogueMode {
  if (typeof window === "undefined") return "simple";
  try {
    const stored = window.localStorage.getItem(CATALOGUE_MODE_STORAGE_KEY);
    return stored === "advanced" ? "advanced" : "simple";
  } catch {
    return "simple";
  }
}

/**
 * Left rail panel: the 27-algorithm catalogue grouped by category.
 *
 * Two display modes:
 *   - Simple Mode (default): flat list of 6 curated, plain-English-labeled
 *     algorithms aimed at the home trader.
 *   - Advanced Mode: the full 6-category accordion exposing all 27.
 *
 * The mode persists in localStorage so the operator's preference survives
 * navigation away from the Quant tab.
 *
 * The data shape comes from `GET /api/execution-algorithms` (6 categories,
 * 27 algorithms total). Names arrive in registry namespace (e.g.
 * `vwap`, `staged_accumulation`); we display them with underscores
 * stripped for readability while still passing the raw name to `onSelect`.
 */
export function AlgorithmCatalogueRail({ selectedAlgorithm, onSelect }: Props) {
  const [catalogue, setCatalogue] = useState<ExecutionAlgorithmCatalogue | null>(null);
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [expandedCategoryId, setExpandedCategoryId] = useState<string | null>(null);
  const [mode, setMode] = useState<CatalogueMode>("simple");

  // Hydrate the mode from localStorage after mount so SSR markup matches.
  useEffect(() => {
    setMode(readStoredMode());
  }, []);

  // Persist mode changes.
  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(CATALOGUE_MODE_STORAGE_KEY, mode);
    } catch {
      // Storage may be disabled (private mode / quota); accept the loss.
    }
  }, [mode]);

  useEffect(() => {
    let cancelled = false;

    listExecutionAlgorithms()
      .then((data) => {
        if (cancelled) return;
        setCatalogue(data);
        setLoadState("ready");
        // Default-expand the first category so the rail isn't fully collapsed
        // when the operator lands on the Quant tab in Advanced Mode.
        if (data.categories.length > 0) {
          setExpandedCategoryId(data.categories[0].id);
        }
      })
      .catch((err) => {
        if (cancelled) return;
        setLoadState("error");
        setErrorMessage(err instanceof Error ? err.message : "Catalogue unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  const totalCount = useMemo(() => catalogue?.total ?? 0, [catalogue]);

  function toggleCategory(id: string) {
    setExpandedCategoryId((current) => (current === id ? null : id));
  }

  function prettifyName(raw: string): string {
    return raw.replaceAll("_", " ");
  }

  return (
    <aside className="quant-catalogue-rail" aria-label="Algorithm catalogue">
      <header className="quant-catalogue-header">
        <span className="panel-kicker">Catalogue</span>
        <h2>Algorithm library</h2>
        {catalogue ? (
          <p className="quant-catalogue-meta">
            {mode === "simple"
              ? `${SIMPLE_MODE_ALGORITHMS.length} essentials`
              : `${totalCount} algorithms · ${catalogue.categories.length} categories`}
          </p>
        ) : null}
      </header>

      <div className="quant-catalogue-modebar">
        <span className="quant-catalogue-modebar-label">Library</span>
        <div
          className="quant-mode-toggle"
          role="tablist"
          aria-label="Catalogue depth"
        >
          <button
            type="button"
            role="tab"
            aria-selected={mode === "simple"}
            data-active={mode === "simple"}
            className="quant-mode-toggle-button"
            onClick={() => setMode("simple")}
          >
            Simple
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={mode === "advanced"}
            data-active={mode === "advanced"}
            className="quant-mode-toggle-button"
            onClick={() => setMode("advanced")}
          >
            Advanced
          </button>
        </div>
      </div>

      {loadState === "loading" ? (
        <p className="quant-catalogue-status">Loading…</p>
      ) : null}

      {loadState === "error" ? (
        <p className="quant-catalogue-status error">
          {errorMessage ?? "Catalogue unavailable"}
        </p>
      ) : null}

      {catalogue && mode === "simple" ? (
        <div
          className="quant-simple-grid"
          role="group"
          aria-label="Essential algorithms"
        >
          {SIMPLE_MODE_ALGORITHMS.map((entry) => {
            const isSelected = entry.name === selectedAlgorithm;
            return (
              <button
                key={entry.name}
                type="button"
                className="quant-simple-tile"
                data-selected={isSelected}
                aria-pressed={isSelected}
                onClick={() => onSelect(entry.name)}
                title={entry.explainer}
              >
                <span className="quant-simple-tile-icon" aria-hidden="true">
                  {entry.icon}
                </span>
                <span className="quant-simple-tile-label">{entry.label}</span>
                <span className="quant-simple-tile-tagline">{entry.tagline}</span>
              </button>
            );
          })}
        </div>
      ) : null}

      {catalogue && mode === "advanced" ? (
        <ul className="quant-catalogue-categories" role="list">
          {catalogue.categories.map((category) => {
            const isExpanded = category.id === expandedCategoryId;
            return (
              <li key={category.id} className="quant-catalogue-category">
                <button
                  type="button"
                  className="quant-catalogue-category-toggle"
                  data-expanded={isExpanded}
                  aria-expanded={isExpanded}
                  onClick={() => toggleCategory(category.id)}
                >
                  <span className="quant-catalogue-category-label">{category.label}</span>
                  <span className="quant-catalogue-category-count">{category.count}</span>
                </button>
                {isExpanded ? (
                  <ul className="quant-catalogue-algorithms" role="list">
                    {category.algorithms.map((algo) => {
                      const isSelected = algo.name === selectedAlgorithm;
                      // Layer in plain-English tooltips for the technical
                      // terms a home trader is unlikely to recognize on sight.
                      // Falls back to the backend description.
                      const tooltip = ADVANCED_ALGO_TOOLTIPS[algo.name] ?? algo.description ?? "";
                      return (
                        <li
                          key={algo.name}
                          className={
                            isSelected
                              ? "quant-catalogue-algorithm selected"
                              : "quant-catalogue-algorithm"
                          }
                        >
                          <button
                            type="button"
                            className="quant-catalogue-algorithm-row"
                            data-selected={isSelected}
                            aria-pressed={isSelected}
                            onClick={() => onSelect(algo.name)}
                            title={tooltip}
                          >
                            {prettifyName(algo.name)}
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                ) : null}
              </li>
            );
          })}
        </ul>
      ) : null}
    </aside>
  );
}
