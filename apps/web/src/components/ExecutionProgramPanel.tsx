"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import {
  appendExecutionProgramEvent,
  createExecutionProgram,
  listExecutionAlgorithms,
  listExecutionProgramEvents,
  listExecutionPrograms,
  previewExecutionAlgorithm
} from "@/lib/api";

import {
  buildExecutionProgramPreview,
  executionProgramTemplates,
  type ExecutionProgramId
} from "@/lib/execution-programs";

import type { ExecutionAlgorithmCatalogue, ExecutionAlgorithmPlan } from "@/lib/types";

type DurableExecutionProgram = {
  algorithm?: string;
  created_at?: string;
  id?: string;
  mode?: string;
  name?: string;
  program_id?: string;
  status?: string;
  symbol?: string;
};

type ExecutionProgramApiStatus =
  | "loading"
  | "ready"
  | "previewing"
  | "saving"
  | "saved"
  | "unavailable";

// Default sizing/reference values used when previewing the registry plan
// before the operator has sized a real ticket. Picked to mirror the
// Desk-prototype's working example so plans render in a familiar shape.
const DEFAULT_NOTIONAL = 1000;
const DEFAULT_REFERENCE_PRICE = 200;
const DEFAULT_SIDE = "buy" as const;

// Frontend "execution programs" predate the backend 27-algorithm registry.
// Only three of the seven legacy template IDs match registered algorithms;
// for those we render accurate operational metadata, for the others we
// fall back to staged_accumulation and flag the fallback in copy.
const LEGACY_TEMPLATE_IDS: ReadonlySet<string> = new Set(
  executionProgramTemplates.map((template) => template.id)
);

const DEFAULT_CATEGORY_ID = "time_based";
const DEFAULT_ALGORITHM_NAME = "vwap";

export function ExecutionProgramPanel({ symbol }: { symbol: string }) {
  // Backend-registered algorithm catalogue (27 across 6 categories).
  const [catalogue, setCatalogue] = useState<ExecutionAlgorithmCatalogue | null>(null);
  const [activeCategoryId, setActiveCategoryId] = useState<string>(DEFAULT_CATEGORY_ID);

  // Currently selected algorithm name (registry namespace).
  const [selectedAlgorithmName, setSelectedAlgorithmName] = useState<string>(DEFAULT_ALGORITHM_NAME);

  // Live execution plan returned by /api/execution-algorithms/preview.
  const [livePlan, setLivePlan] = useState<ExecutionAlgorithmPlan | null>(null);

  // Legacy frontend-template id, used only for operational metadata panels
  // (triggers / circuit breakers / lifecycle / missing provider facts).
  // Kept in sync with the catalogue selection when the names match; falls
  // back to staged_accumulation otherwise.
  const [legacyAlgorithmId, setLegacyAlgorithmId] = useState<ExecutionProgramId>(
    "staged_accumulation"
  );

  const [apiStatus, setApiStatus] = useState<ExecutionProgramApiStatus>("loading");
  const [eventCount, setEventCount] = useState(0);
  const [savedPrograms, setSavedPrograms] = useState<DurableExecutionProgram[]>([]);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const normalizedSymbol = useMemo(() => normalizeSymbol(symbol), [symbol]);
  const recentPrograms = savedPrograms.slice(0, 3);

  const legacyPreview = useMemo(
    () => buildExecutionProgramPreview({ algorithmId: legacyAlgorithmId, symbol: normalizedSymbol }),
    [legacyAlgorithmId, normalizedSymbol]
  );

  const hasLegacyMetadata = LEGACY_TEMPLATE_IDS.has(selectedAlgorithmName);

  // Load the 27-algorithm catalogue once on mount.
  useEffect(() => {
    let cancelled = false;

    listExecutionAlgorithms()
      .then((data) => {
        if (cancelled) return;
        setCatalogue(data);
        setApiStatus("ready");
      })
      .catch((err) => {
        if (cancelled) return;
        setCatalogue(null);
        setApiStatus("unavailable");
        setErrorMessage(err instanceof Error ? err.message : "Catalogue unavailable");
      });

    return () => {
      cancelled = true;
    };
  }, []);

  // Whenever the selected algorithm or symbol changes, fetch a fresh live plan.
  useEffect(() => {
    if (!selectedAlgorithmName || !normalizedSymbol) return;
    let cancelled = false;
    setApiStatus("previewing");
    previewExecutionAlgorithm({
      algorithm: selectedAlgorithmName,
      symbol: normalizedSymbol,
      side: DEFAULT_SIDE,
      notional: DEFAULT_NOTIONAL,
      referencePrice: DEFAULT_REFERENCE_PRICE
    })
      .then((plan) => {
        if (cancelled) return;
        setLivePlan(plan);
        setApiStatus("ready");
        setErrorMessage(null);
      })
      .catch((err) => {
        if (cancelled) return;
        setLivePlan(null);
        setApiStatus("unavailable");
        setErrorMessage(err instanceof Error ? err.message : "Preview unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [selectedAlgorithmName, normalizedSymbol]);

  // Load recent saved programs for this symbol.
  useEffect(() => {
    let isCurrent = true;

    async function loadRecentPrograms() {
      try {
        const catalog = await listExecutionPrograms({ limit: 5, symbol: normalizedSymbol });
        const programs = Array.isArray(catalog) ? catalog : catalog.programs ?? [];
        if (isCurrent) {
          setSavedPrograms(programs);
        }
      } catch {
        if (isCurrent) {
          setSavedPrograms([]);
        }
      }
    }

    void loadRecentPrograms();

    return () => {
      isCurrent = false;
    };
  }, [normalizedSymbol]);

  const activeCategoryAlgorithms = useMemo(() => {
    if (!catalogue) return [];
    return catalogue.categories.find((c) => c.id === activeCategoryId)?.algorithms ?? [];
  }, [catalogue, activeCategoryId]);

  const handleSelectAlgorithm = useCallback((algoName: string) => {
    setSelectedAlgorithmName(algoName);
    if (LEGACY_TEMPLATE_IDS.has(algoName)) {
      setLegacyAlgorithmId(algoName as ExecutionProgramId);
    }
  }, []);

  async function savePaperPreview() {
    if (!livePlan) return;
    setApiStatus("saving");
    try {
      const created = await createExecutionProgram({
        algorithmId: livePlan.algorithm,
        approvalStatus: "required",
        circuitBreakers: livePlan.policy_notes.map((note) => ({ rule: note })),
        liveSubmissionEnabled: false,
        missingProviderFacts: legacyPreview.missingProviderFacts,
        mode: "paper",
        payload: livePlan,
        state: "preview_ready",
        symbol: livePlan.symbol,
        triggerPoints: legacyPreview.triggerPoints.map((trigger) => ({
          condition: trigger.condition,
          label: trigger.label,
          type: trigger.type
        }))
      });
      const programId = created.program_id;
      await appendExecutionProgramEvent(programId, {
        eventType: "preview_created",
        summary: `Preview created from algorithm registry: ${livePlan.algorithm}. No live trade submission.`
      });
      const events = await listExecutionProgramEvents(programId);
      const normalizedEvents = Array.isArray(events) ? events : events.events ?? [];
      setEventCount(normalizedEvents.length);
      setSavedPrograms((current) =>
        [created, ...current.filter((program) => (program.program_id ?? program.id) !== programId)].slice(0, 5)
      );
      setApiStatus("saved");
    } catch (err) {
      setSavedPrograms((current) => [
        {
          algorithm: livePlan.algorithm,
          created_at: new Date().toISOString(),
          mode: "paper",
          name: `${livePlan.symbol} ${livePlan.algorithm} local preview`,
          program_id: `local-${livePlan.symbol}-${livePlan.algorithm}`,
          status: "local_only",
          symbol: livePlan.symbol
        },
        ...current
      ]);
      setApiStatus("unavailable");
      setErrorMessage(err instanceof Error ? err.message : "Durable API unavailable");
    }
  }

  return (
    <article className="dashboard-home-panel execution-program-panel" aria-label="Execution Program Monitor">
      <div className="dashboard-panel-title">
        <span className="panel-kicker">Execution Program Monitor</span>
        <span className="panel-control-dot" aria-hidden="true" />
      </div>
      <div className="execution-program-header">
        <div>
          <h2>{normalizedSymbol} execution program</h2>
          <p>
            {livePlan
              ? `${livePlan.algorithm} · ${livePlan.legs.length} legs · ${livePlan.estimated_quantity} est. units`
              : "Select an algorithm below to preview a deterministic plan from the registry."}
          </p>
        </div>
        <div className="execution-program-state" aria-label="Paper and approval state">
          <span>Paper mode</span>
          <span>Approval required</span>
          <span>No live trade submission</span>
        </div>
      </div>

      {/* Algorithm picker: tabbed cards, 27 algorithms from the backend registry. */}
      <section className="algo-catalogue" aria-label="Algorithm catalogue">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Algorithm</span>
          {catalogue && (
            <span className="algo-catalogue-meta">
              {catalogue.total} algorithms · {catalogue.categories.length} categories
            </span>
          )}
        </div>
        {!catalogue && apiStatus === "loading" && <p>Loading algorithm catalogue…</p>}
        {!catalogue && apiStatus === "unavailable" && (
          <p className="error">Catalogue unavailable: {errorMessage ?? "Unknown error"}</p>
        )}
        {catalogue && (
          <>
            <div className="algo-catalogue-tabs" role="tablist">
              {catalogue.categories.map((cat) => (
                <button
                  key={cat.id}
                  role="tab"
                  type="button"
                  aria-selected={cat.id === activeCategoryId}
                  className="algo-catalogue-tab"
                  data-active={cat.id === activeCategoryId}
                  onClick={() => setActiveCategoryId(cat.id)}
                >
                  {cat.label}
                  <span className="algo-catalogue-tab-count">{cat.count}</span>
                </button>
              ))}
            </div>
            <div className="algo-catalogue-grid" role="tabpanel">
              {activeCategoryAlgorithms.map((algo) => (
                <button
                  key={algo.name}
                  type="button"
                  className="algo-catalogue-card"
                  data-selected={algo.name === selectedAlgorithmName}
                  onClick={() => handleSelectAlgorithm(algo.name)}
                >
                  <div className="algo-catalogue-card-head">
                    <strong>{algo.name}</strong>
                    <span className="algo-catalogue-card-dot" aria-hidden="true" />
                  </div>
                  <p>{algo.description}</p>
                </button>
              ))}
            </div>
          </>
        )}
      </section>

      {/* Live plan returned by /api/execution-algorithms/preview. */}
      {livePlan && (
        <section className="algo-live-plan" aria-label="Live algorithm plan">
          <div className="dashboard-panel-title">
            <span className="panel-kicker">Plan · {livePlan.algorithm}</span>
            <span className="algo-live-plan-meta">
              {livePlan.legs.length} legs · paper preview
            </span>
          </div>
          <div className="algo-live-plan-summary">
            <div>
              <span className="panel-kicker">Side</span>
              <strong>{livePlan.side.toUpperCase()}</strong>
            </div>
            <div>
              <span className="panel-kicker">Notional</span>
              <strong>${livePlan.notional.toLocaleString()}</strong>
            </div>
            <div>
              <span className="panel-kicker">Est. quantity</span>
              <strong>{livePlan.estimated_quantity}</strong>
            </div>
            <div>
              <span className="panel-kicker">Reference</span>
              <strong>${livePlan.reference_price}</strong>
            </div>
          </div>
          <table className="algo-live-plan-legs">
            <thead>
              <tr>
                <th>Kind</th>
                <th>Side</th>
                <th>Qty</th>
                <th>Price</th>
                <th>Notional</th>
              </tr>
            </thead>
            <tbody>
              {livePlan.legs.length === 0 ? (
                <tr>
                  <td colSpan={5}>Gated out — algorithm refused to size up at current parameters.</td>
                </tr>
              ) : (
                livePlan.legs.map((leg, idx) => (
                  <tr key={`${leg.kind}-${idx}`}>
                    <td>{leg.kind.replaceAll("_", " ")}</td>
                    <td>{leg.side}</td>
                    <td>{leg.estimated_quantity}</td>
                    <td>{leg.price !== null ? `$${leg.price}` : "—"}</td>
                    <td>${leg.notional}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
          {livePlan.policy_notes.length > 0 && (
            <ul className="algo-live-plan-notes">
              {livePlan.policy_notes.map((note, i) => (
                <li key={`policy-${i}`}>{note}</li>
              ))}
            </ul>
          )}
        </section>
      )}

      <div className="dashboard-command-actions">
        <button
          className="primary-button"
          type="button"
          onClick={savePaperPreview}
          disabled={!livePlan || apiStatus === "saving"}
        >
          {apiStatus === "saving" ? "Saving preview..." : "Save paper preview"}
        </button>
        <button className="micro-action-button" type="button" disabled>
          Live trade submission disabled
        </button>
      </div>
      <p className={apiStatus === "unavailable" ? "error" : "run-id"}>
        {apiStatus === "saved"
          ? `Saved paper preview. preview_created lifecycle event recorded${eventCount > 0 ? ` (${eventCount} events)` : ""}.`
          : apiStatus === "unavailable"
            ? "Durable API unavailable. Showing local paper preview only; no live trade submission is possible here."
            : "Paper preview only. Approval is required before any broker route."}
      </p>

      {/* Operational metadata — accurate for the 3 legacy IDs
       * (bracket_order / trailing_stop / dca_ladder); for the other 24
       * algorithms this surface renders the staged_accumulation fallback
       * shape and the fallback is flagged in copy. */}
      <section className="execution-program-summary" aria-label="Selected algorithm">
        <div>
          <span className="panel-kicker">Algorithm</span>
          <strong>{legacyPreview.algorithm.name}</strong>
          <small>
            {hasLegacyMetadata
              ? legacyPreview.algorithm.desk
              : "Operational profile pending — fallback template shown"}
          </small>
        </div>
        <div>
          <span className="panel-kicker">State</span>
          <strong>{legacyPreview.state.mode}</strong>
          <small>{legacyPreview.state.approvalGate}</small>
        </div>
        <div>
          <span className="panel-kicker">Cadence</span>
          <strong>{legacyPreview.algorithm.cadence}</strong>
          <small>{legacyPreview.state.liveSubmissionEnabled ? "Live route enabled" : "No live trade submission"}</small>
        </div>
      </section>
      <section className="execution-program-triggers" aria-label="Triggers">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Triggers</span>
        </div>
        <ul>
          {legacyPreview.triggerPoints.map((trigger) => (
            <li key={trigger.type}>
              <strong>{trigger.label}</strong>
              <span>{trigger.type}</span>
              <small>{trigger.condition}</small>
            </li>
          ))}
        </ul>
      </section>
      <section className="execution-program-breakers" aria-label="Circuit breakers">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Circuit breakers</span>
        </div>
        <ul>
          {legacyPreview.circuitBreakers.map((breaker) => (
            <li key={breaker}>{breaker}</li>
          ))}
        </ul>
      </section>
      <section className="execution-program-timeline" aria-label="Lifecycle timeline">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Lifecycle timeline</span>
        </div>
        <ol>
          {legacyPreview.expectedEvents.map((event) => (
            <li key={event.phase}>
              <strong>{event.phase.replaceAll("_", " ")}</strong>
              <span>{event.summary}</span>
            </li>
          ))}
        </ol>
      </section>
      <section className="execution-program-timeline" aria-label="Recent saved programs">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Recent saved programs</span>
        </div>
        {recentPrograms.length > 0 ? (
          <ol>
            {recentPrograms.map((program) => (
              <li key={program.program_id ?? program.id ?? `${program.symbol}-${program.algorithm}`}>
                <strong>{program.name ?? `${program.symbol ?? normalizedSymbol} ${program.algorithm ?? "execution"} program`}</strong>
                <span>{program.status ?? program.mode ?? "paper preview saved"}</span>
              </li>
            ))}
          </ol>
        ) : (
          <p>No recent durable programs for {normalizedSymbol} yet.</p>
        )}
      </section>
      <section className="execution-program-provider-facts" aria-label="Missing provider facts">
        <div className="dashboard-panel-title">
          <span className="panel-kicker">Missing provider facts</span>
        </div>
        <ul>
          {legacyPreview.missingProviderFacts.map((fact) => (
            <li key={fact}>{fact}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}

function normalizeSymbol(symbol: string): string {
  const normalized = symbol.trim().toUpperCase();
  return normalized.length > 0 ? normalized : "WATCHLIST";
}
