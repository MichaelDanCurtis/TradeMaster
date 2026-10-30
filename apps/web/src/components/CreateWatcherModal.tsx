"use client";

/**
 * CreateWatcherModal — modal form to create a Watcher. Summoned from the
 * SymbolDetailDrawer's "Set watcher" button (with symbol pre-filled and
 * locked) and from any positions/watchers list. Reuses the existing
 * .info-modal-backdrop / .info-modal chrome.
 */

import { useEffect, useId, useMemo, useState } from "react";

import { createWatcher } from "@/lib/api";
import type { WatcherConditionType, WatcherRecord } from "@/lib/types";

const CONDITION_OPTIONS: { value: WatcherConditionType; label: string; thresholdHint: string }[] = [
  { value: "price_above", label: "Price above", thresholdHint: "Price (USD)" },
  { value: "price_below", label: "Price below", thresholdHint: "Price (USD)" },
  { value: "change_pct_above", label: "Day change % above", thresholdHint: "Percent (e.g. 5)" },
  { value: "change_pct_below", label: "Day change % below", thresholdHint: "Percent (e.g. -3)" },
  { value: "volume_above", label: "Volume above", thresholdHint: "Volume (shares)" }
];

const CONDITION_PHRASE: Record<WatcherConditionType, string> = {
  price_above: "above",
  price_below: "below",
  change_pct_above: "Δ% above",
  change_pct_below: "Δ% below",
  volume_above: "vol above"
};

function suggestName(symbol: string, condition: WatcherConditionType, threshold: string): string {
  const symbolUpper = symbol.trim().toUpperCase();
  if (!symbolUpper || !threshold) return "";
  return `${symbolUpper} ${CONDITION_PHRASE[condition]} ${threshold}`;
}

export type CreateWatcherModalProps = {
  isOpen: boolean;
  /** When provided, the symbol field is locked to this value. */
  lockedSymbol?: string | null;
  /** Initial symbol value (used when lockedSymbol is absent). */
  initialSymbol?: string;
  /** Optional position to link the watcher to. */
  linkedPositionId?: string | null;
  /** Optional run to link the watcher to. */
  linkedRunId?: string | null;
  onClose: () => void;
  onCreated: (watcher: WatcherRecord) => void;
};

export function CreateWatcherModal({
  isOpen,
  lockedSymbol,
  initialSymbol = "",
  linkedPositionId = null,
  linkedRunId = null,
  onClose,
  onCreated
}: CreateWatcherModalProps) {
  const formId = useId();
  const [symbol, setSymbol] = useState<string>("");
  const [condition, setCondition] = useState<WatcherConditionType>("price_above");
  const [threshold, setThreshold] = useState<string>("");
  const [name, setName] = useState<string>("");
  const [nameTouched, setNameTouched] = useState<boolean>(false);
  const [cooldownSeconds, setCooldownSeconds] = useState<string>("300");
  const [showAdvanced, setShowAdvanced] = useState<boolean>(false);
  const [submitting, setSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // Initialize / reset form on open.
  useEffect(() => {
    if (!isOpen) return;
    const seed = (lockedSymbol ?? initialSymbol ?? "").toUpperCase();
    setSymbol(seed);
    setCondition("price_above");
    setThreshold("");
    setName("");
    setNameTouched(false);
    setCooldownSeconds("300");
    setShowAdvanced(false);
    setSubmitting(false);
    setError(null);
  }, [isOpen, lockedSymbol, initialSymbol]);

  // Auto-suggest name unless the user has edited it.
  useEffect(() => {
    if (nameTouched) return;
    setName(suggestName(symbol, condition, threshold));
  }, [symbol, condition, threshold, nameTouched]);

  // Close on Escape.
  useEffect(() => {
    if (!isOpen) return;
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape" && !submitting) {
        onClose();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, onClose, submitting]);

  const activeCondition = useMemo(
    () => CONDITION_OPTIONS.find((entry) => entry.value === condition) ?? CONDITION_OPTIONS[0],
    [condition]
  );

  if (!isOpen) return null;

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);

    const symbolValue = symbol.trim().toUpperCase();
    if (!symbolValue) {
      setError("Symbol is required.");
      return;
    }
    const thresholdNumber = Number(threshold);
    if (!Number.isFinite(thresholdNumber)) {
      setError("Threshold must be a number.");
      return;
    }
    const nameValue = name.trim() || suggestName(symbolValue, condition, threshold) || `${symbolValue} watcher`;
    const cooldownNumber = Number(cooldownSeconds);
    const cooldown = Number.isFinite(cooldownNumber) && cooldownNumber >= 0 ? cooldownNumber : 300;

    setSubmitting(true);
    try {
      const watcher = await createWatcher({
        name: nameValue,
        symbol: symbolValue,
        conditionType: condition,
        threshold: thresholdNumber,
        enabled: true,
        cooldownSeconds: cooldown,
        linkedPositionId,
        linkedRunId
      });
      onCreated(watcher);
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Failed to create watcher");
      setSubmitting(false);
    }
  }

  const symbolFieldLocked = Boolean(lockedSymbol);

  return (
    <div
      aria-label="Create watcher"
      aria-modal="true"
      className="info-modal-backdrop create-watcher-modal-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget && !submitting) {
          onClose();
        }
      }}
      role="dialog"
    >
      <div className="info-modal create-watcher-modal">
        <header className="info-modal-header create-watcher-modal-header">
          <div>
            <span className="panel-kicker">Watcher · arm rule</span>
            <h2>Set a watcher{symbol ? ` on ${symbol}` : ""}</h2>
          </div>
          <button
            aria-label="Close create watcher"
            className="symbol-detail-drawer-close"
            disabled={submitting}
            onClick={onClose}
            type="button"
          >
            <span aria-hidden="true">×</span>
          </button>
        </header>
        <div className="info-modal-body create-watcher-modal-body">
          <form className="create-watcher-form" id={formId} onSubmit={handleSubmit}>
            <label className="create-watcher-field">
              <span>Symbol</span>
              <input
                aria-label="Symbol"
                autoFocus={!symbolFieldLocked}
                disabled={symbolFieldLocked || submitting}
                onChange={(event) => setSymbol(event.target.value.toUpperCase())}
                placeholder="NVDA"
                required
                type="text"
                value={symbol}
              />
            </label>
            <label className="create-watcher-field">
              <span>Condition</span>
              <select
                aria-label="Condition type"
                disabled={submitting}
                onChange={(event) => setCondition(event.target.value as WatcherConditionType)}
                value={condition}
              >
                {CONDITION_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="create-watcher-field">
              <span>Threshold</span>
              <input
                aria-label="Threshold"
                autoFocus={symbolFieldLocked}
                disabled={submitting}
                inputMode="decimal"
                onChange={(event) => setThreshold(event.target.value)}
                placeholder={activeCondition.thresholdHint}
                required
                step="any"
                type="number"
                value={threshold}
              />
            </label>
            <label className="create-watcher-field">
              <span>Name</span>
              <input
                aria-label="Watcher name"
                disabled={submitting}
                onChange={(event) => {
                  setNameTouched(true);
                  setName(event.target.value);
                }}
                placeholder="auto-named from symbol + rule"
                type="text"
                value={name}
              />
            </label>

            <button
              aria-expanded={showAdvanced}
              className="create-watcher-advanced-toggle"
              onClick={() => setShowAdvanced((prior) => !prior)}
              type="button"
            >
              {showAdvanced ? "Hide" : "Show"} advanced
            </button>

            {showAdvanced ? (
              <label className="create-watcher-field">
                <span>Cooldown (seconds)</span>
                <input
                  aria-label="Cooldown seconds"
                  disabled={submitting}
                  inputMode="numeric"
                  min={0}
                  onChange={(event) => setCooldownSeconds(event.target.value)}
                  step="1"
                  type="number"
                  value={cooldownSeconds}
                />
                <small>
                  Minimum gap between fires for the same rule. Default 300 (5 minutes).
                </small>
              </label>
            ) : null}

            {error ? (
              <p className="create-watcher-error" role="alert">
                {error}
              </p>
            ) : null}

            <footer className="create-watcher-actions">
              <button
                className="create-watcher-cancel"
                disabled={submitting}
                onClick={onClose}
                type="button"
              >
                Cancel
              </button>
              <button
                className="primary-button create-watcher-submit"
                disabled={submitting || !symbol.trim() || !threshold}
                type="submit"
              >
                {submitting ? "Arming…" : "Arm watcher"}
              </button>
            </footer>
          </form>
        </div>
      </div>
    </div>
  );
}
