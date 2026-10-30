"use client";

import { useEffect, useState } from "react";

import { AgentRunGraph } from "@/components/AgentRunGraph";
import { ExecutionProgramPanel } from "@/components/ExecutionProgramPanel";
import { FundingAllocationPanel } from "@/components/FundingAllocationPanel";
// RoomRoadmapPanel removed in the 4-tab IA flattening (2026-05-20).
import { TradeTicket } from "@/components/TradeTicket";
import {
  createAgentTrigger,
  createRun,
  listExecutionAlgorithms,
  listPortfolioAccounts,
  listRunEvents,
  previewExecutionAlgorithm,
  previewTrade
} from "@/lib/api";
import type {
  ExecutionAlgorithm,
  ExecutionAlgorithmCatalogue,
  ExecutionAlgorithmPlan,
  OrderPreview,
  OrderSide,
  PortfolioAccount,
  RunEvent
} from "@/lib/types";

type PolicyStatus = "idle" | "passed" | "blocked";

type AccountState =
  | { phase: "loading" }
  | { phase: "live"; account: PortfolioAccount }
  | { phase: "fallback"; reason: "no-creds" | "api-error" };

const fmtAccountMoney = (n: number | null | undefined) =>
  n === null || n === undefined
    ? "—"
    : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function TransactionsWorkspace({ symbol }: { symbol: string }) {
  const [algorithm, setAlgorithm] = useState<ExecutionAlgorithm>("bracket_order");
  const [side, setSide] = useState<OrderSide>("buy");
  const [notional, setNotional] = useState(1000);
  const [runId, setRunId] = useState<string | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [preview, setPreview] = useState<OrderPreview | null>(null);
  const [algorithmPlan, setAlgorithmPlan] = useState<ExecutionAlgorithmPlan | null>(null);
  const [isPreviewing, setIsPreviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [policyStatus, setPolicyStatus] = useState<PolicyStatus>("idle");
  const [executionTriggerStatus, setExecutionTriggerStatus] = useState<"idle" | "armed" | "failed">("idle");

  // Algorithm catalogue (all 27, fetched on mount). Replaces the hand-coded
  // 3-option dropdown — algorithm selection in this room should expose the
  // full library since this is where orders are actually composed.
  const [catalogue, setCatalogue] = useState<ExecutionAlgorithmCatalogue | null>(null);
  const [accountState, setAccountState] = useState<AccountState>({ phase: "loading" });

  useEffect(() => {
    let isCurrent = true;
    listExecutionAlgorithms()
      .then((cat) => {
        if (isCurrent) setCatalogue(cat);
      })
      .catch(() => {
        // Keep null; the dropdown will render an empty state.
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  useEffect(() => {
    let isCurrent = true;
    setAccountState({ phase: "loading" });
    listPortfolioAccounts("alpaca-paper-broker")
      .then((catalog) => {
        if (!isCurrent) return;
        const first = catalog.accounts[0];
        if (first) {
          setAccountState({ phase: "live", account: first });
        } else {
          setAccountState({ phase: "fallback", reason: "no-creds" });
        }
      })
      .catch((caught: Error & { status?: number }) => {
        if (!isCurrent) return;
        setAccountState({
          phase: "fallback",
          reason: caught.status === 403 || caught.status === 404 ? "no-creds" : "api-error"
        });
      });
    return () => {
      isCurrent = false;
    };
  }, []);

  async function runPaperAlgorithmPreview() {
    setIsPreviewing(true);
    setError(null);
    setPolicyStatus("idle");
    setRunId(null);
    setEvents([]);
    setPreview(null);
    setAlgorithmPlan(null);
    setExecutionTriggerStatus("idle");

    try {
      const created = await createRun({
        brokerMode: "paper",
        executionMode: "real",
        ticker: symbol,
        tradeDate: new Date().toISOString().slice(0, 10)
      });
      const [nextEvents, nextPreview] = await Promise.all([
        listRunEvents(created.run_id),
        previewTrade({
          notional,
          runId: created.run_id,
          side,
          symbol
        })
      ]);
      const nextAlgorithmPlan = await previewExecutionAlgorithm({
        algorithm,
        notional,
        referencePrice: nextPreview.estimated_price,
        side,
        symbol
      });
      setRunId(created.run_id);
      setEvents(nextEvents);
      setPreview(nextPreview);
      setAlgorithmPlan(nextAlgorithmPlan);
      await createAgentTrigger({
        condition: {
          algorithm,
          max_notional: notional,
          reference_price: nextPreview.estimated_price,
          side,
          source: "execution_algorithm_preview"
        },
        name: `${symbol} ${algorithm.replaceAll("_", " ")} risk monitor`,
        payload: {
          algorithm,
          estimated_quantity: nextAlgorithmPlan.estimated_quantity,
          order_intent_id: nextPreview.intent_id,
          run_id: created.run_id
        },
        roomId: "market",
        symbol,
        targetAgent: "execution-risk-agent",
        triggerType: "risk_threshold",
        workflowId: created.run_id
      });
      setExecutionTriggerStatus("armed");
      setPolicyStatus("passed");
    } catch (caught) {
      const message = caught instanceof Error ? caught.message : "Unable to preview paper execution";
      setError(message);
      setExecutionTriggerStatus("failed");
      setPolicyStatus(message.includes("symbolic constraints vetoed order") ? "blocked" : "idle");
    } finally {
      setIsPreviewing(false);
    }
  }

  return (
    <section className="transactions-workspace" aria-label="Execution agents workspace">
      <div className="transactions-main">
        <header className="workspace-header transactions-header">
          <div>
            <span className="panel-kicker">Private Office</span>
            <h1>{symbol} operations and execution review</h1>
          </div>
          <span className="status-pill paper">PyReason gated</span>
        </header>

        <section className="transaction-balance-strip" aria-label="Broker account status">
          {accountState.phase === "live" ? (
            <>
              <Metric label="Equity" value={fmtAccountMoney(accountState.account.current_balance)} />
              <Metric
                label="Account"
                value={accountState.account.mask ? `…${accountState.account.mask}` : accountState.account.name}
              />
              <Metric label="Currency" value={accountState.account.iso_currency_code ?? "USD"} />
              <Metric label="Mode" value="Paper · live data" />
            </>
          ) : accountState.phase === "loading" ? (
            <>
              <Metric label="Equity" value="…" />
              <Metric label="Account" value="…" />
              <Metric label="Currency" value="…" />
              <Metric label="Mode" value="Paper preview" />
            </>
          ) : (
            <>
              <Metric
                label="Equity"
                value={accountState.reason === "no-creds" ? "Enable Alpaca" : "API offline"}
              />
              <Metric
                label="Account"
                value={accountState.reason === "no-creds" ? "Set ALPACA_API_KEY" : "—"}
              />
              <Metric label="Currency" value="USD" />
              <Metric label="Mode" value="Paper preview" />
            </>
          )}
        </section>

        <FundingAllocationPanel symbol={symbol} notional={notional} />

        <div className="transaction-grid">
          <section className="transaction-panel">
            <PanelHeading kicker="Broker adapter" title="Alpaca paper algorithm" count={preview ? 1 : 0} />
            <p>
              This runs a paper-mode execution preview from the current research stance. Broker submission remains blocked until
              the ticket is explicitly approved.
            </p>
            <div className="execution-control-grid">
              <label>
                <span>Execution algorithm</span>
                <select
                  value={algorithm}
                  onChange={(event) => setAlgorithm(event.target.value as ExecutionAlgorithm)}
                >
                  {catalogue
                    ? catalogue.categories.map((category) => (
                        <optgroup key={category.id} label={category.label}>
                          {category.algorithms.map((algo) => (
                            <option key={algo.name} value={algo.name}>
                              {algo.name.replaceAll("_", " ")}
                            </option>
                          ))}
                        </optgroup>
                      ))
                    : (
                      <>
                        <option value="bracket_order">Bracket order</option>
                        <option value="trailing_stop">Trailing stop</option>
                        <option value="dca_ladder">DCA ladder</option>
                      </>
                    )}
                </select>
              </label>
              <label>
                <span>Side</span>
                <select value={side} onChange={(event) => setSide(event.target.value as OrderSide)}>
                  <option value="buy">Buy</option>
                  <option value="sell">Sell</option>
                </select>
              </label>
              <label>
                <span>Notional</span>
                <input
                  min={1}
                  max={1_000_000_000}
                  onChange={(event) => setNotional(Number(event.target.value))}
                  step={100}
                  type="number"
                  value={notional}
                />
              </label>
              <button className="primary-button" type="button" onClick={runPaperAlgorithmPreview} disabled={isPreviewing}>
                {isPreviewing ? "Previewing..." : `Preview ${symbol} paper order`}
              </button>
            </div>
            {runId ? <p className="run-id">Run {runId}</p> : null}
            {executionTriggerStatus === "armed" ? <p className="run-id">Execution trigger armed</p> : null}
            {executionTriggerStatus === "failed" && policyStatus === "passed" ? <p className="error">Execution trigger failed to arm.</p> : null}
            {error ? <p className="error">{error}</p> : null}
            {algorithmPlan ? <AlgorithmPlanPanel plan={algorithmPlan} /> : null}
          </section>

          <section className="transaction-panel">
            <PanelHeading kicker="Symbolic safety" title="Circuit breakers" count={policyStatus === "passed" ? 1 : 0} />
            <PolicyGatePanel status={policyStatus} error={error} />
            <AgentRunGraph events={events} />
          </section>
        </div>

        {/* Full library browser. The dropdown above sets the algorithm used by
         * the order-preview flow; this panel below lets the operator skim all
         * 27 algorithms, see live legs/policy notes for any of them, and save
         * promoted programs. Moved here from MarketAtGlanceWorkspace because
         * order composition is where algorithm selection actually matters. */}
        <ExecutionProgramPanel symbol={symbol} />
      </div>

      <aside className="transaction-approval-rail">
        {/* RoomRoadmapPanel removed in the 4-tab IA flattening (2026-05-20). */}
        <section className="approval-intent-panel">
          <PanelHeading kicker="Execution policy" title={preview ? "Paper ticket ready" : "No pending order"} />
          {preview ? (
            <TradeTicket preview={preview} />
          ) : (
            <>
              <p>
                Research agents may recommend. Execution agents must prove policy compliance before paper or broker actions can be
                approved.
              </p>
              <span className="approval-badge required">Approval required</span>
            </>
          )}
        </section>
      </aside>
    </section>
  );
}

function PolicyGatePanel({ error, status }: { error: string | null; status: PolicyStatus }) {
  const label =
    status === "passed" ? "Policy check passed" : status === "blocked" ? "Policy blocked" : "Awaiting preview";
  return (
    <section className={`policy-gate-panel ${status}`} aria-label="Execution policy status">
      <div>
        <span className="panel-kicker">Symbolic policy active</span>
        <strong>{label}</strong>
      </div>
      <ul>
        <li>Paper brokerage mode is mandatory.</li>
        <li>Default cap: 10% max position, 35% max sector, 20% daily turnover.</li>
        <li>Human approval remains required before broker submission.</li>
      </ul>
      {status === "blocked" && error ? <p>{error}</p> : null}
    </section>
  );
}

function AlgorithmPlanPanel({ plan }: { plan: ExecutionAlgorithmPlan }) {
  return (
    <section className="algorithm-plan-panel" aria-label="Algorithm legs">
      <div className="section-title">
        <span>Algorithm legs</span>
        <strong>{plan.legs.length}</strong>
      </div>
      <div className="algorithm-leg-list">
        {plan.legs.map((leg, index) => (
          <article className="algorithm-leg" key={`${leg.kind}-${index}`}>
            <span>{leg.kind.replaceAll("_", " ")}</span>
            <strong>{leg.price === null ? "market" : `$${leg.price.toFixed(2)}`}</strong>
            <small>
              {leg.side.toUpperCase()} ${leg.notional.toLocaleString()} / {leg.estimated_quantity}
            </small>
          </article>
        ))}
      </div>
      <ul>
        {plan.policy_notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>
    </section>
  );
}

function PanelHeading({ kicker, title, count }: { kicker: string; title: string; count?: number }) {
  return (
    <header className="panel-header">
      <div>
        <span className="panel-kicker">{kicker}</span>
        <h2>{title}</h2>
      </div>
      {typeof count === "number" ? <span className="panel-count">{count}</span> : null}
    </header>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}
