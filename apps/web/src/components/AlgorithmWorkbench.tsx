"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ExecutionScheduler } from "@/components/ExecutionScheduler";
import { TradeTicket } from "@/components/TradeTicket";
import { SIMPLE_MODE_ALGORITHMS } from "@/components/AlgorithmCatalogueRail";
import {
  listExecutionAlgorithms,
  previewExecutionAlgorithm,
  previewTrade
} from "@/lib/api";
import type {
  ExecutionAlgorithmCatalogue,
  ExecutionAlgorithmCatalogueEntry,
  ExecutionAlgorithmPlan,
  OrderSide,
  OrderPreview
} from "@/lib/types";

type ApiPhase = "idle" | "previewing" | "preparing" | "prepared" | "error";

type Props = {
  algorithm: string | null;
  symbol: string;
  /**
   * Research→execution side handoff. When QuantWorkbench applies an approved
   * idea it bumps `token`; the workbench sets the side control once per token
   * and otherwise leaves the user's manual side selection alone.
   */
  sideIntent?: { side: OrderSide; token: number } | null;
};

const DEFAULT_NOTIONAL = 1000;
const DEFAULT_REFERENCE_PRICE = 200;
const DEFAULT_SIDE: OrderSide = "buy";

/**
 * Backend `category` IDs use snake_case; the workbench classification line
 * wants uppercase hyphenated traders' language. Map the common cases
 * explicitly so they read like a TradingView taxonomy; fall back to a
 * naive uppercase-with-hyphens transform for anything unmapped.
 */
const CATEGORY_CLASSIFICATION: Record<string, string> = {
  liquidity_taking: "LIQUIDITY-TAKING",
  liquidity_providing: "LIQUIDITY-PROVIDING",
  time_weighted: "TIME-SLICED",
  volume_weighted: "VOLUME-WEIGHTED",
  risk_management: "RISK MANAGEMENT",
  event_driven: "EVENT-DRIVEN",
  adaptive: "ADAPTIVE",
  accumulation: "ACCUMULATION",
  bracket: "BRACKET",
  pegged: "PEGGED",
  hidden: "DARK / HIDDEN"
};

function classifyCategory(category: string | null | undefined): string | null {
  if (!category) return null;
  if (CATEGORY_CLASSIFICATION[category]) return CATEGORY_CLASSIFICATION[category];
  return category.replaceAll("_", "-").toUpperCase();
}

/** Analytical algorithm previews plus a separately reviewed exact manual order. */
export function AlgorithmWorkbench({ algorithm, symbol, sideIntent }: Props) {
  const [catalogue, setCatalogue] = useState<ExecutionAlgorithmCatalogue | null>(null);

  // Param state.
  const [notional, setNotional] = useState<number>(DEFAULT_NOTIONAL);
  const [side, setSide] = useState<OrderSide>(DEFAULT_SIDE);
  const [referencePrice, setReferencePrice] = useState<number>(DEFAULT_REFERENCE_PRICE);

  // Apply a research→execution side handoff exactly once per token, so the
  // user can still flip the side manually afterwards without it snapping back.
  const appliedSideTokenRef = useRef<number | null>(null);
  useEffect(() => {
    if (!sideIntent) return;
    if (appliedSideTokenRef.current === sideIntent.token) return;
    appliedSideTokenRef.current = sideIntent.token;
    setSide(sideIntent.side);
  }, [sideIntent]);

  // Protective-stop envelope. Both fields are optional; only when at
  // least one is set do we promote the figures to `broker_protective`
  // so the Alpaca adapter sends a bracket / OTO order. Empty inputs
  // ("") produce a plain exact limit order.
  const [stopLossInput, setStopLossInput] = useState<string>("");
  const [takeProfitInput, setTakeProfitInput] = useState<string>("");

  // Plan + chain state.
  const [plan, setPlan] = useState<ExecutionAlgorithmPlan | null>(null);
  const [apiPhase, setApiPhase] = useState<ApiPhase>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const ticketGeneration = useRef(0);
  const [exactPreview, setExactPreview] = useState<OrderPreview | null>(null);

  // Expand the explainer to show the full backend description below the
  // curated one-liner. Collapsed by default.
  const [explainerExpanded, setExplainerExpanded] = useState<boolean>(false);

  // Mounted tracker — keeps Approve & Submit and manual Preview from
  // dispatching setState after the component unmounts mid-chain.
  const mountedRef = useRef(true);
  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  // Load the catalogue once so we can resolve category + description for
  // the currently selected algorithm. No need to refetch per selection.
  useEffect(() => {
    let cancelled = false;
    listExecutionAlgorithms()
      .then((data) => {
        if (!cancelled) setCatalogue(data);
      })
      .catch(() => {
        // Selection will still work; we just won't show category/description.
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Resolve the currently selected algorithm's metadata from the catalogue.
  const selectedMeta = useMemo<{
    entry: ExecutionAlgorithmCatalogueEntry | null;
    categoryLabel: string | null;
  }>(() => {
    if (!algorithm || !catalogue) return { entry: null, categoryLabel: null };
    for (const category of catalogue.categories) {
      const entry = category.algorithms.find((a) => a.name === algorithm);
      if (entry) {
        return { entry, categoryLabel: category.label };
      }
    }
    return { entry: null, categoryLabel: null };
  }, [algorithm, catalogue]);

  // Curated Simple Mode metadata (icon + explainer) if the selected algorithm
  // is one of the curated 6. The workbench uses this for both the header icon
  // and the leading explainer line.
  const curatedSimple = useMemo(() => {
    if (!algorithm) return null;
    return SIMPLE_MODE_ALGORITHMS.find((entry) => entry.name === algorithm) ?? null;
  }, [algorithm]);

  // Plain-English explainer for the callout above the parameter form.
  // Prefer the curated Simple Mode copy; fall back to the backend description
  // when the operator has selected an Advanced Mode algorithm without a
  // curated explainer.
  const explainerText = useMemo<string | null>(() => {
    if (!algorithm) return null;
    if (curatedSimple) return curatedSimple.explainer;
    return selectedMeta.entry?.description ?? null;
  }, [algorithm, curatedSimple, selectedMeta]);

  // Backend `category` ID from the catalogue, mapped to a trader-readable
  // uppercase classification line (e.g. "EXECUTION · LIQUIDITY-TAKING").
  const classificationLine = useMemo<string | null>(() => {
    const classification = classifyCategory(selectedMeta.entry?.category);
    if (!classification) return null;
    return `EXECUTION · ${classification}`;
  }, [selectedMeta]);

  // Algorithm name in display form (e.g. "Market buy/sell"). Prefer the
  // curated Simple Mode label; otherwise un-snake-case the backend name.
  const displayName = useMemo<string | null>(() => {
    if (!algorithm) return null;
    if (curatedSimple) return curatedSimple.label;
    return algorithm.replaceAll("_", " ");
  }, [algorithm, curatedSimple]);

  // Collapse the explainer when the algorithm changes — keeps the
  // "What this does" expander pristine for each new selection.
  useEffect(() => {
    setExplainerExpanded(false);
  }, [algorithm]);

  /**
   * Compute the protective-stop envelope derived from the two text
   * inputs.
   *
   *   - parsed numbers (or null when the input is blank / invalid)
   *   - whether the bracket is full (both set), half (one set), or off
   *   - a validation error message when the BUY/SELL relationship is
   *     wrong relative to the reference price
   *
   * The reference price is used as the validation anchor — same value
   * the algorithm preview uses, so the operator sees consistent gates.
   */
  const bracket = useMemo(() => {
    const parse = (raw: string): number | null => {
      const trimmed = raw.trim();
      if (trimmed === "") return null;
      const value = Number(trimmed);
      return Number.isFinite(value) && value > 0 ? value : null;
    };
    const stopLoss = parse(stopLossInput);
    const takeProfit = parse(takeProfitInput);
    const bothSet = stopLoss !== null && takeProfit !== null;
    const eitherSet = stopLoss !== null || takeProfit !== null;
    let validation: string | null = null;
    if (eitherSet && referencePrice > 0) {
      if (side === "buy") {
        if (stopLoss !== null && stopLoss >= referencePrice) {
          validation = `Stop loss must be below the reference price ($${referencePrice}).`;
        } else if (takeProfit !== null && takeProfit <= referencePrice) {
          validation = `Take profit must be above the reference price ($${referencePrice}).`;
        }
      } else {
        // SELL: take_profit < current < stop_loss
        if (stopLoss !== null && stopLoss <= referencePrice) {
          validation = `Stop loss must be above the reference price ($${referencePrice}) on a sell.`;
        } else if (takeProfit !== null && takeProfit >= referencePrice) {
          validation = `Take profit must be below the reference price ($${referencePrice}) on a sell.`;
        }
      }
    }
    return { stopLoss, takeProfit, bothSet, eitherSet, validation };
  }, [stopLossInput, takeProfitInput, referencePrice, side]);

  // Run a preview whenever the algorithm, symbol, or params change.
  const runPreview = useCallback(async () => {
    if (!algorithm) {
      setPlan(null);
      return;
    }
    setApiPhase("previewing");
    setErrorMessage(null);
    try {
      const next = await previewExecutionAlgorithm({
        algorithm,
        symbol,
        side,
        notional,
        referencePrice
      });
      setPlan(next);
      setApiPhase("idle");
    } catch (err) {
      setPlan(null);
      setApiPhase("error");
      setErrorMessage(err instanceof Error ? err.message : "Preview failed");
    }
  }, [algorithm, symbol, side, notional, referencePrice]);

  useEffect(() => {
    if (!algorithm) return;
    let cancelled = false;
    setApiPhase("previewing");
    setErrorMessage(null);
    previewExecutionAlgorithm({
      algorithm,
      symbol,
      side,
      notional,
      referencePrice
    })
      .then((next) => {
        if (cancelled) return;
        setPlan(next);
        setApiPhase("idle");
      })
      .catch((err) => {
        if (cancelled) return;
        setPlan(null);
        setApiPhase("error");
        setErrorMessage(err instanceof Error ? err.message : "Preview failed");
      });
    return () => {
      cancelled = true;
    };
  }, [algorithm, symbol, side, notional, referencePrice]);

  useEffect(() => {
    ticketGeneration.current += 1;
    setExactPreview(null);
    setApiPhase((phase) => phase === "preparing" ? "idle" : phase);
  }, [algorithm, symbol, side, notional, referencePrice, stopLossInput, takeProfitInput]);

  async function prepareExactOrder() {
    if (!algorithm) return;
    if (bracket.validation) {
      setApiPhase("error");
      setErrorMessage(bracket.validation);
      return;
    }
    const generation = ++ticketGeneration.current;
    setApiPhase("preparing");
    setExactPreview(null);
    setErrorMessage(null);
    try {
      // Only attach a risk_controls envelope when the operator filled
      // at least one leg. Empty inputs keep the legacy market path
      // (advisory_only on the broker side).
      const preview = await previewTrade({
        symbol,
        side,
        notional,
        riskControls: bracket.eitherSet
          ? {
              stop_loss: bracket.stopLoss,
              take_profit: bracket.takeProfit,
              mode: "broker_protective"
            }
          : undefined
      });
      if (!mountedRef.current || generation !== ticketGeneration.current) return;
      setExactPreview(preview);
      setApiPhase("prepared");
    } catch (err) {
      if (!mountedRef.current || generation !== ticketGeneration.current) return;
      setApiPhase("error");
      setErrorMessage(err instanceof Error ? err.message : "Exact preview failed");
    }
  }

  const isWorking = apiPhase === "previewing" || apiPhase === "preparing";
  const workingLabel =
    apiPhase === "previewing"
      ? "Working… previewing plan"
      : apiPhase === "preparing"
      ? "Working… preparing exact order"
      : null;

  return (
    <section className="quant-workbench-panel" aria-label="Algorithm workbench">
      {/* --- Header: kicker / name+icon / classification ------------------ */}
      <header className="quant-workbench-header-v2">
        <span className="quant-workbench-header-kicker">Algorithm</span>
        {algorithm && displayName ? (
          <>
            <h2 className="quant-workbench-header-name">
              <span className="quant-workbench-header-name-text">{displayName}</span>
              {curatedSimple ? (
                <span className="quant-workbench-header-icon" aria-hidden="true">
                  {curatedSimple.icon}
                </span>
              ) : null}
            </h2>
            {classificationLine ? (
              <span className="quant-workbench-classification">{classificationLine}</span>
            ) : selectedMeta.categoryLabel ? (
              <span className="quant-workbench-classification">
                {selectedMeta.categoryLabel.toUpperCase()}
              </span>
            ) : null}
          </>
        ) : (
          <>
            <h2 className="quant-workbench-header-name">
              <span className="quant-workbench-header-name-text">No algorithm selected</span>
            </h2>
            <span className="quant-workbench-classification">
              PICK FROM THE CATALOGUE — START WITH MARKET BUY/SELL
            </span>
          </>
        )}
      </header>

      {/* --- Explainer callout: leading line + expandable detail ---------- */}
      {explainerText ? (
        <aside
          className="quant-explainer-callout-v2"
          role="note"
          aria-label="Algorithm explainer"
        >
          <span className="quant-explainer-callout-v2-icon" aria-hidden="true">
            i
          </span>
          <div className="quant-explainer-callout-v2-body">
            <p className="quant-explainer-callout-v2-lead">{explainerText}</p>
            {selectedMeta.entry?.description &&
            selectedMeta.entry.description !== explainerText ? (
              <>
                <button
                  type="button"
                  className="quant-explainer-callout-v2-expander"
                  onClick={() => setExplainerExpanded((value) => !value)}
                  aria-expanded={explainerExpanded}
                >
                  {explainerExpanded ? "Hide details" : "What this does"}
                </button>
                {explainerExpanded ? (
                  <p className="quant-explainer-callout-v2-detail">
                    {selectedMeta.entry.description}
                  </p>
                ) : null}
              </>
            ) : null}
          </div>
        </aside>
      ) : null}

      {/* --- Parameters: 3-col grid + segmented side + $ prefix ----------- */}
      <fieldset className="quant-workbench-params" disabled={!algorithm}>
        <legend className="panel-kicker">Parameters</legend>
        <div className="quant-param-grid">
          <label
            className="quant-param-cell help"
            title="Notional = the dollar amount you want to trade. The system computes the share count from this and the current price."
          >
            <span className="quant-param-cell-label">Notional</span>
            <span className="quant-param-input-prefix">
              <span className="quant-param-input-prefix-symbol" aria-hidden="true">
                $
              </span>
              <input
                type="number"
                min={1}
                max={1_000_000_000}
                step={100}
                value={notional}
                onChange={(event) => setNotional(Number(event.target.value))}
                title="Notional = the dollar amount you want to trade. The system computes the share count from this and the current price."
              />
            </span>
            <span className="quant-param-cell-hint">USD value to trade.</span>
          </label>

          <div
            className="quant-param-cell"
            title="Buy grows a position. Sell reduces owned shares; this ticket does not support short selling."
          >
            <span className="quant-param-cell-label">Side</span>
            <div
              className="quant-side-segmented"
              role="radiogroup"
              aria-label="Order side"
            >
              <button
                type="button"
                role="radio"
                aria-checked={side === "buy"}
                data-active={side === "buy"}
                data-tone="buy"
                className="quant-side-segmented-button"
                onClick={() => setSide("buy")}
                disabled={!algorithm}
              >
                Buy
              </button>
              <button
                type="button"
                role="radio"
                aria-checked={side === "sell"}
                data-active={side === "sell"}
                data-tone="sell"
                className="quant-side-segmented-button"
                onClick={() => setSide("sell")}
                disabled={!algorithm}
              >
                Sell
              </button>
            </div>
            <span className="quant-param-cell-hint">Direction of the order.</span>
          </div>

          <label
            className="quant-param-cell help"
            title="The price the algorithm uses as its anchor for plan computation."
          >
            <span className="quant-param-cell-label">Reference price</span>
            <span className="quant-param-input-prefix">
              <span className="quant-param-input-prefix-symbol" aria-hidden="true">
                $
              </span>
              <input
                type="number"
                min={0.01}
                step={0.01}
                value={referencePrice}
                onChange={(event) => setReferencePrice(Number(event.target.value))}
                title="The price the algorithm uses as its anchor for plan computation."
              />
            </span>
            <span className="quant-param-cell-hint">Anchor used by the plan.</span>
          </label>
        </div>
        {/* --- Protective stop row -------------------------------------
         * Both inputs are optional. When both are set we promote to a
         * full bracket order on submit; when one is set we send an OTO.
         * Empty inputs preserve the legacy market-only path. */}
        <div className="quant-param-grid quant-bracket-row" style={{ marginTop: "0.75rem" }}>
          <label
            className="quant-param-cell help"
            title="Stop loss in dollars. Sent to Alpaca as the stop_price on a protective child order."
          >
            <span className="quant-param-cell-label">Stop loss ($)</span>
            <span className="quant-param-input-prefix">
              <span className="quant-param-input-prefix-symbol" aria-hidden="true">
                $
              </span>
              <input
                type="number"
                min={0}
                step={0.01}
                value={stopLossInput}
                placeholder="optional"
                onChange={(event) => setStopLossInput(event.target.value)}
                aria-label="Stop loss in dollars (optional)"
              />
            </span>
            <span className="quant-param-cell-hint">Protective sell-stop price.</span>
          </label>

          <label
            className="quant-param-cell help"
            title="Take profit in dollars. Sent to Alpaca as the limit_price on a take-profit child order."
          >
            <span className="quant-param-cell-label">Take profit ($)</span>
            <span className="quant-param-input-prefix">
              <span className="quant-param-input-prefix-symbol" aria-hidden="true">
                $
              </span>
              <input
                type="number"
                min={0}
                step={0.01}
                value={takeProfitInput}
                placeholder="optional"
                onChange={(event) => setTakeProfitInput(event.target.value)}
                aria-label="Take profit in dollars (optional)"
              />
            </span>
            <span className="quant-param-cell-hint">Limit price for the profit leg.</span>
          </label>
        </div>

        {/* --- Bracket-mode hint ---------------------------------------
         * Green when both legs are set (full bracket), amber when one
         * (OTO), red when validation fails. Stays mute when neither is
         * set so the panel doesn't shout at operators who don't want
         * broker-side risk controls. */}
        {bracket.validation ? (
          <p
            className="quant-bracket-hint"
            role="alert"
            style={{
              marginTop: "0.5rem",
              padding: "0.5rem 0.75rem",
              borderLeft: "3px solid #c0392b",
              background: "rgba(192, 57, 43, 0.08)",
              fontSize: "0.85rem"
            }}
          >
            {bracket.validation}
          </p>
        ) : bracket.bothSet ? (
          <p
            className="quant-bracket-hint"
            role="status"
            style={{
              marginTop: "0.5rem",
              padding: "0.5rem 0.75rem",
              borderLeft: "3px solid #2f7d4f",
              background: "rgba(47, 125, 79, 0.08)",
              fontSize: "0.85rem"
            }}
          >
            Bracket order — broker submits SL + TP alongside entry.
          </p>
        ) : bracket.eitherSet ? (
          <p
            className="quant-bracket-hint"
            role="status"
            style={{
              marginTop: "0.5rem",
              padding: "0.5rem 0.75rem",
              borderLeft: "3px solid #b8860b",
              background: "rgba(184, 134, 11, 0.08)",
              fontSize: "0.85rem"
            }}
          >
            Attached protective stop — single child order.
          </p>
        ) : null}

        <p className="quant-workbench-param-note">
          Reference price is a manual scenario input, initially $200, not a current quote. Parameters not shown here use the algorithm’s defaults.
        </p>
      </fieldset>

      {/* --- Plan card: promoted centerpiece ------------------------------ */}
      <section className="quant-plan-card" aria-label="Execution plan">
        <header className="quant-plan-card-header">
          <div className="quant-plan-card-header-left">
            <span className="panel-kicker">Execution plan</span>
            {plan ? (
              <span className="quant-plan-card-subtitle">
                ref{" "}
                <span className="quant-plan-card-ref">
                  ${referencePrice.toLocaleString(undefined, { maximumFractionDigits: 2 })}
                </span>
              </span>
            ) : null}
          </div>
          {plan ? (
            <div className="quant-plan-card-meta">
              <span className="quant-plan-card-meta-pill">
                <span className="quant-plan-card-meta-key">Legs</span>
                <span className="quant-plan-card-meta-value">{plan.legs.length}</span>
              </span>
              <span className="quant-plan-card-meta-pill">
                <span className="quant-plan-card-meta-key">Est. qty</span>
                <span className="quant-plan-card-meta-value">
                  {plan.estimated_quantity}
                </span>
              </span>
            </div>
          ) : null}
        </header>

        {apiPhase === "previewing" && !plan ? (
          <p className="quant-plan-card-empty">Previewing…</p>
        ) : null}
        {!algorithm ? (
          <p className="quant-plan-card-empty">
            Select an algorithm to preview a deterministic plan.
          </p>
        ) : null}

        {plan ? (
          <>
            <div className="quant-plan-table-wrap">
              <table className="quant-plan-table">
                <thead>
                  <tr>
                    <th>Kind</th>
                    <th>Side</th>
                    <th className="quant-plan-table-num">Qty</th>
                    <th className="quant-plan-table-num">Price</th>
                    <th className="quant-plan-table-num">Notional</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.legs.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="quant-plan-table-empty-row">
                        Gated out — algorithm refused to size at current parameters.
                      </td>
                    </tr>
                  ) : (
                    plan.legs.map((leg, idx) => (
                      <tr key={`${leg.kind}-${idx}`}>
                        <td className="quant-plan-table-kind">
                          {leg.kind.replaceAll("_", " ")}
                        </td>
                        <td className="quant-plan-table-side" data-side={leg.side}>
                          {leg.side}
                        </td>
                        <td className="quant-plan-table-num">{leg.estimated_quantity}</td>
                        <td className="quant-plan-table-num">
                          {leg.price !== null ? `$${leg.price}` : (
                            <span className="quant-plan-table-null">—</span>
                          )}
                        </td>
                        <td className="quant-plan-table-num">
                          ${leg.notional.toLocaleString()}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
            {plan.policy_notes.length > 0 ? (
              <ul className="quant-plan-card-notes">
                {plan.policy_notes.map((note, i) => (
                  <li key={`note-${i}`}>{note}</li>
                ))}
              </ul>
            ) : null}
          </>
        ) : algorithm && apiPhase !== "previewing" ? (
          <div className="quant-plan-card-empty-state">
            <p className="quant-plan-card-empty-headline">Preview to see legs</p>
            <button
              type="button"
              className="secondary-button quant-plan-card-empty-button"
              onClick={runPreview}
              disabled={isWorking}
            >
              Preview
            </button>
          </div>
        ) : null}
      </section>

      <section className="quant-workbench-constraints" aria-label="Account checks">
        <span className="panel-kicker">Account checks</span>
        <p>Exact order preparation checks current cash, holdings, pending orders, concentration and drawdown. Submission checks them again after your approval.</p>
        <p>The algorithm above is an analytical preview. The ticket below prepares one manual limit order; it does not execute the algorithm’s schedule or multiple legs.</p>
      </section>

      {/* --- Actions row: Preview / Approve & Submit / PAPER pill --------- */}
      <div className="quant-actions-row">
        {isWorking ? (
          <span className="quant-actions-row-working" role="status">
            <span className="quant-actions-row-working-dot" aria-hidden="true" />
            {workingLabel}
          </span>
        ) : (
          <div className="quant-actions-row-buttons">
            <button
              type="button"
              className="secondary-button quant-actions-preview-button"
              onClick={runPreview}
              disabled={!algorithm || isWorking}
            >
              Preview
            </button>
            <button
              type="button"
              className="primary-button quant-actions-submit-button"
              onClick={prepareExactOrder}
              disabled={!algorithm || !plan || isWorking}
            >
              Prepare exact paper order
            </button>
          </div>
        )}
        {/* Paper-mode reminder. The Approve & submit chain hard-codes
         * brokerMode: "paper" — make that visible so the operator never
         * mistakes the workbench for a live-money surface. */}
        <span
          className="quant-paper-badge-v2"
          role="status"
          aria-label="Paper trading mode — no real money"
          title="Paper mode = simulated trades against Alpaca's paper account. No real money is moved."
        >
          <span className="quant-paper-badge-v2-mark" aria-hidden="true">
            ⚠
          </span>
          PAPER
        </span>
      </div>

      <ExecutionScheduler algorithm={algorithm} symbol={symbol} side={side} notional={notional} referencePrice={referencePrice} protectiveInputs={Boolean(stopLossInput.trim() || takeProfitInput.trim())} />

      {exactPreview ? <TradeTicket key={exactPreview.intent_id} preview={exactPreview} /> : null}
      {apiPhase === "error" && errorMessage ? (
        <p className="quant-workbench-status error">{errorMessage}</p>
      ) : null}
    </section>
  );
}
