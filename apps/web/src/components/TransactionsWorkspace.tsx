"use client";

import { useState } from "react";

import { getTransactionSnapshot, type TransactionOrder, type TransactionOrderIntent, type TransactionPosition } from "@/lib/workspace-data";

export function TransactionsWorkspace({ symbol }: { symbol: string }) {
  const snapshot = getTransactionSnapshot(symbol);
  const investedValue = snapshot.positions.reduce((total, position) => total + position.marketValue, 0);
  const paperCashBalance = snapshot.portfolioValue - investedValue;

  return (
    <section className="transactions-workspace" aria-label="Transactions workspace">
      <div className="transactions-main">
        <header className="workspace-header transactions-header">
          <div>
            <span className="panel-kicker">Paper portfolio</span>
            <h1>{snapshot.symbol} transactions</h1>
          </div>
          <span className="status-pill paper">Approval gated</span>
        </header>

        <section className="transaction-balance-strip" aria-label="Paper account snapshot">
          <Metric label="Portfolio value" value={formatCurrency(snapshot.portfolioValue)} />
          <Metric label="Paper cash balance" value={formatCurrency(paperCashBalance)} />
          <Metric label="Buying power" value={formatCurrency(snapshot.buyingPower)} />
          <Metric label="Mode" value={snapshot.mode} />
        </section>

        <div className="transaction-grid">
          <section className="transaction-panel">
            <PanelHeading kicker="Holdings" title="Top positions" count={snapshot.positions.length} />
            <div className="position-list">
              {snapshot.positions.map((position) => (
                <PositionRow key={position.symbol} position={position} />
              ))}
            </div>
          </section>

          <section className="transaction-panel">
            <PanelHeading kicker="Activity" title="Recent orders" count={snapshot.recentOrders.length} />
            <div className="order-list">
              {snapshot.recentOrders.map((order) => (
                <OrderRow key={order.id} order={order} />
              ))}
            </div>
          </section>
        </div>
      </div>

      <aside className="transaction-approval-rail">
        <section className="approval-intent-panel">
          <PanelHeading kicker="Open intent" title="Paper approval request" />
          <dl className="intent-detail-list">
            <div>
              <dt>Intent</dt>
              <dd>{snapshot.orderIntent.id}</dd>
            </div>
            <div>
              <dt>Side</dt>
              <dd>{snapshot.orderIntent.side.toUpperCase()}</dd>
            </div>
            <div>
              <dt>Limit reference</dt>
              <dd>{formatCurrency(snapshot.orderIntent.limitPrice)}</dd>
            </div>
            <div>
              <dt>Confidence</dt>
              <dd>{formatPercent(snapshot.orderIntent.confidence)}</dd>
            </div>
          </dl>
          <p>{snapshot.orderIntent.rationale}</p>
          <span className="approval-badge required">
            {snapshot.orderIntent.requiresApproval ? "Approval required" : "Preview only"}
          </span>
        </section>

        <SeededPaperTicket key={snapshot.orderIntent.id} intent={snapshot.orderIntent} />
      </aside>
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

function PositionRow({ position }: { position: TransactionPosition }) {
  return (
    <article className="position-row">
      <div>
        <strong>{position.symbol}</strong>
        <span>{position.quantity.toLocaleString()} shares</span>
      </div>
      <div>
        <strong>{formatCurrency(position.marketValue)}</strong>
        <span className={position.dayChangePercent >= 0 ? "positive" : "negative"}>
          {formatSignedPercent(position.dayChangePercent)}
        </span>
      </div>
    </article>
  );
}

function OrderRow({ order }: { order: TransactionOrder }) {
  return (
    <article className="order-row">
      <div>
        <strong>
          {order.side.toUpperCase()} {order.symbol}
        </strong>
        <span>{formatDateTime(order.submittedAt)}</span>
      </div>
      <div>
        <strong>{order.quantity.toLocaleString()} sh</strong>
        <span className={`order-status ${order.status}`}>{order.status}</span>
      </div>
    </article>
  );
}

function SeededPaperTicket({ intent }: { intent: TransactionOrderIntent }) {
  const [status, setStatus] = useState<"previewed" | "staged">("previewed");
  const estimatedQuantity = intent.notional / intent.limitPrice;
  const isStaged = status === "staged";

  return (
    <section className="seeded-paper-ticket">
      <header className="ticket-header">
        <div>
          <span className="mode-pill">Paper preview</span>
          <h2>Seeded paper ticket</h2>
        </div>
        <span className={isStaged ? "ticket-status submitted" : "ticket-status"}>{isStaged ? "staged" : status}</span>
      </header>
      <dl>
        <div>
          <dt>Symbol</dt>
          <dd>{intent.symbol}</dd>
        </div>
        <div>
          <dt>Side</dt>
          <dd>{intent.side.toUpperCase()}</dd>
        </div>
        <div>
          <dt>Notional</dt>
          <dd>{formatCurrency(intent.notional)}</dd>
        </div>
        <div>
          <dt>Estimated quantity</dt>
          <dd>{estimatedQuantity.toFixed(4)}</dd>
        </div>
      </dl>
      <button className="primary-button" type="button" onClick={() => setStatus("staged")} disabled={isStaged}>
        {isStaged ? "Paper order staged locally" : "Stage paper order"}
      </button>
      <p className="muted">
        Local seeded preview only. This control does not contact a broker or submit through the trading API.
      </p>
    </section>
  );
}

function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  }).format(value);
}

function formatPercent(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "percent",
    maximumFractionDigits: 0
  }).format(value);
}

function formatSignedPercent(value: number): string {
  const formatted = `${Math.abs(value).toFixed(1)}%`;

  return value >= 0 ? `+${formatted}` : `-${formatted}`;
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(value));
}
