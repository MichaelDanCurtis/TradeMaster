"use client";

import { useEffect, useState } from "react";
import { approveAccountBaseline, listAccountReconciliations, listObservedPaperAccounts, previewAccountBaseline, reconcileObservedAccount } from "@/lib/accounting";
import type { AccountBaseline, AccountReconciliation, AccountingPoint, AccountingReport, ObservedPaperAccount } from "@/lib/accounting";
import { DeploymentExecutionHistory } from "./DeploymentExecutionHistory";
import { DeploymentPerformancePanel } from "./DeploymentPerformancePanel";
import { SourceCorrectionsPanel } from "./SourceCorrectionsPanel";

const money = (value: string | null | undefined) => value == null ? "Unavailable" : Number(value).toLocaleString("en-US", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 6 });
const percent = (value: string | null | undefined) => value == null ? "Unavailable" : `${(Number(value)*100).toLocaleString("en-US", {maximumFractionDigits:4})}%`;
const date = (value: string) => new Date(value).toLocaleString();
const ownerName = (value: string) => ({manual:"Manual orders",external_manual:"External manual orders",legacy_manual:"Holdings at opening",unattributed_income:"Unallocated account income",unattributed_fees:"Unallocated account fees"}[value] ?? (value.startsWith("deployment:") ? "Strategy deployment" : value.startsWith("schedule:") ? "Execution schedule" : value));

export function PerformanceWorkspace({ symbol }: { symbol: string }) {
  const [accounts,setAccounts] = useState<ObservedPaperAccount[]>([]);
  const [selected,setSelected] = useState("");
  const [preview,setPreview] = useState<AccountBaseline | null>(null);
  const [receipts,setReceipts] = useState<AccountReconciliation[]>([]);
  const [loading,setLoading] = useState(true);
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState<string | null>(null);
  useEffect(() => {
    let active=true;
    listObservedPaperAccounts().then(({accounts: rows})=>{if(active){setAccounts(rows);setSelected(rows[0]?.enrollment.account_key ?? "");}})
      .catch((caught)=>{if(active)setError(caught instanceof Error ? caught.message : "Account history unavailable");})
      .finally(()=>{if(active)setLoading(false);});
    return ()=>{active=false;};
  },[]);
  const account=accounts.find((row)=>row.enrollment.account_key===selected);
  const report=account?.latest?.report;

  async function act(action: "preview" | "approve" | "reconcile" | "reload" | "history") {
    setBusy(true);setError(null);
    try {
      if(action==="preview") setPreview(await previewAccountBaseline());
      if(action==="approve" && preview) {await approveAccountBaseline(preview);setSelected(preview.account_key);setPreview(null);}
      if(action==="reconcile" && selected) await reconcileObservedAccount(selected);
      if(action==="history" && selected) setReceipts((await listAccountReconciliations(selected)).reconciliations);
      if(action!=="preview" && action!=="history") {
        const next=(await listObservedPaperAccounts()).accounts;
        setAccounts(next);setSelected((current)=>next.some((row)=>row.enrollment.account_key===current) ? current : next[0]?.enrollment.account_key ?? "");
      }
    } catch(caught) {setError(caught instanceof Error ? caught.message : "Account action failed");}
    finally {setBusy(false);}
  }

  return <section className="performance-workspace paper-accounting" aria-label="Performance" aria-busy={busy || loading} data-active-symbol={symbol}>
    <header className="workspace-header"><div><span className="panel-kicker">Portfolio · Performance</span><h1>Reconciled account history</h1></div></header>
    <p>Track investment P&amp;L separately from money added or withdrawn. Every observation keeps its source records and reconciliation result.</p>
    <div className="paper-accounting-actions">
      <button className="secondary-button" onClick={()=>act("reload")} disabled={busy || loading}>Refresh saved history</button>
      <button className="secondary-button" onClick={()=>act("preview")} disabled={busy || loading}>Review opening account snapshot</button>
    </div>
    {loading && <p role="status">Loading saved accounts…</p>}
    {error && <p className="error" role="alert">{error}</p>}
    {!loading && !accounts.length && <div className="paper-accounting-card"><h2>No observation period yet</h2><p>Review the configured paper account to establish a starting point. No historical performance will be invented from its current balance.</p></div>}
    {preview && <section className="paper-accounting-card" aria-label="Review account baseline">
      <span className="mode-pill">{preview.snapshot.evidence_kind==="fixture" ? "Fixture simulation" : "Broker paper account"}</span>
      <h2>Review the starting account balance</h2>
      <dl className="paper-accounting-metrics"><div><dt>Account</dt><dd>{preview.snapshot.account_id}</dd></div><div><dt>Equity</dt><dd>{money(preview.snapshot.equity_usd)}</dd></div><div><dt>Cash</dt><dd>{money(preview.snapshot.cash_usd)}</dd></div><div><dt>Observed</dt><dd>{date(preview.snapshot.observed_at)}</dd></div></dl>
      <p>Measurement starts at this snapshot. Earlier gains and losses are excluded. This starting point is permanent for this account; approving it does not authorize an order or move money.</p>
      {preview.snapshot.evidence_kind==="fixture" && <p>These balances belong to the local test fixture. They provide no broker or investment evidence.</p>}
      {preview.snapshot.limitations?.map((line)=><p key={line} className="muted">{line}</p>)}
      <p>{preview.snapshot.positions.length} opening positions. Approve before {date(preview.expires_at)}.</p>
      {preview.snapshot.positions.length>0 && <div className="paper-accounting-table"><table><thead><tr><th>Symbol</th><th>Quantity</th><th>Market value</th><th>Broker basis</th></tr></thead><tbody>{preview.snapshot.positions.map((p)=><tr key={p.symbol}><td>{p.symbol}</td><td>{p.quantity}</td><td>{money(p.market_value_usd)}</td><td>{money(p.cost_basis_usd)}</td></tr>)}</tbody></table></div>}
      <div className="paper-accounting-actions"><button className="primary-button" onClick={()=>act("approve")} disabled={busy}>Approve observation baseline</button><button className="secondary-button" onClick={()=>setPreview(null)} disabled={busy}>Dismiss preview</button></div>
    </section>}
    {accounts.length>0 && <label className="paper-accounting-select">Observed account<select value={selected} onChange={(event)=>{setSelected(event.target.value);setReceipts([]);}} disabled={busy}>{accounts.map((row)=><option key={row.enrollment.account_key} value={row.enrollment.account_key}>{row.enrollment.account_id} · {row.baseline.snapshot.evidence_kind==="fixture" ? "fixture" : "broker paper"}</option>)}</select></label>}
    {account && <>
      <section className="paper-accounting-card">
        <span className="mode-pill">{account.baseline.snapshot.evidence_kind==="fixture" ? "Fixture simulation" : "Broker paper observations"}</span>
        <h2>{report ? report.reconciled ? "Account reconciled" : "Reconciliation needs attention" : "Baseline approved"}</h2>
        <p>Observation period starts {date(account.baseline.snapshot.observed_at)}. {report ? `Latest observation: ${date(report.observed_at)}.` : "Read current broker activity to record the first comparison."}</p>
        <div className="paper-accounting-actions"><button className="primary-button" onClick={()=>act("reconcile")} disabled={busy}>Reconcile account and outstanding orders</button><button className="secondary-button" onClick={()=>act("history")} disabled={busy}>Inspect reconciliation history</button></div>
        <p className="muted">Reconciliation looks up existing orders and reads account activity. It does not submit new orders.</p>
      </section>
      {report && <AccountReport report={report} />}
      <SourceCorrectionsPanel key={`corrections-${account.enrollment.account_key}`} accountKey={account.enrollment.account_key} refreshKey={account.latest?.reconciliation_id}/>
      <DeploymentExecutionHistory key={account.enrollment.account_key} accountKey={account.enrollment.account_key} refreshKey={account.latest?.reconciliation_id}/>
      <DeploymentPerformancePanel key={`returns-${account.enrollment.account_key}`} accountKey={account.enrollment.account_key} refreshKey={account.latest?.reconciliation_id}/>
      {receipts.length>0 && <details open className="paper-accounting-card"><summary>Saved reconciliation receipts ({receipts.length})</summary><ul>{receipts.map((item)=><li key={item.reconciliation_id}>{date(item.created_at)} · {item.report.reconciled ? "reconciled" : "discrepancies retained"} · {item.report.activity_count} source activities</li>)}</ul></details>}
    </>}
  </section>;
}

function AccountReport({report}:{report:AccountingReport}) {
  return <>
    <section className="paper-accounting-card" aria-label="Account performance summary">
      <dl className="paper-accounting-metrics">
        <div><dt>Observed equity</dt><dd>{money(report.equity_usd)}</dd></div><div><dt>Investment P&amp;L since opening</dt><dd>{money(report.investment_pnl_usd)}</dd></div>
        <div><dt>Net deposits / withdrawals</dt><dd>{money(report.net_external_flows_usd)}</dd></div><div><dt>Time-weighted return</dt><dd>{percent(report.time_weighted_return_fraction)}</dd></div>
        <div><dt>Current observed drawdown</dt><dd>{percent(report.drawdown_fraction)}</dd></div><div><dt>Maximum observed drawdown</dt><dd>{percent(report.maximum_drawdown_fraction)}</dd></div>
        <div><dt>Recorded income</dt><dd>{money(report.income_usd)}</dd></div><div><dt>Recorded fees</dt><dd>{money(report.fees_usd)}</dd></div>
      </dl>
      {report.reporting_rounding_change_usd != null && <p>Change from broker reporting precision: {money(report.reporting_rounding_change_usd)}. This is included in account equity changes and excluded from strategy attribution.</p>}
      {report.drawdown_fraction==null && <p role="status">New entries are blocked while reconciled drawdown is unavailable. A funded reduction can still be reviewed.</p>}
      <p className="muted">Returns and drawdown cover observed valuations since the reviewed baseline. Unobserved intraday peaks are not inferred. Analytical cost estimates are excluded from broker cash.</p>
      {report.discrepancies.length>0 && <div role="alert"><h3>Unresolved discrepancies</h3><ul>{report.discrepancies.map((item,index)=><li key={`${item.code}-${index}`}>{item.code.replaceAll("_"," ")}{item.symbol ? ` · ${item.symbol}` : ""}{item.detail ? `: ${item.detail}` : ""}{item.expected_usd!=null ? ` · expected ${money(item.expected_usd)}, observed ${money(item.observed_usd)}` : ""}</li>)}</ul></div>}
      {report.limitations.length>0 && <details><summary>Methods and missing evidence</summary><ul>{report.limitations.map((line,index)=><li key={`${index}-${line}`}>{line}</li>)}</ul></details>}
    </section>
    <section className="paper-accounting-card"><h2>Observed account equity</h2><p>Includes deposits and withdrawals. Use time-weighted return above for investment performance.</p><EquityHistory points={report.equity_history} /></section>
    <section className="paper-accounting-card"><h2>Position and income attribution</h2><p>FIFO assigns an exit to the owners of the lots sold, including an exit placed manually. Opening unrealized gains are removed from period P&amp;L. Cash income without ownership evidence stays unallocated.</p>
      {report.attribution.length ? <div className="paper-accounting-table"><table><thead><tr><th>Owner</th><th>FIFO realized</th><th>Unrealized</th><th>Income</th><th>Fees</th><th>Period P&amp;L</th></tr></thead><tbody>{report.attribution.map((row)=><tr key={row.owner}><td title={row.owner}>{ownerName(row.owner)}</td><td>{money(row.realized_pnl_usd)}</td><td>{money(row.unrealized_pnl_usd)}</td><td>{money(row.income_usd)}</td><td>{money(row.fees_usd)}</td><td>{report.reconciled ? money(row.period_pnl_usd) : "Unreconciled"}</td></tr>)}</tbody></table></div> : <p>No attributable fills or income since opening.</p>}
      <p className="muted">Analytical FIFO basis may differ from the broker method. This is not a tax report.</p>
    </section>
    {(report.open_orders.length>0 || report.outstanding_execution.length>0) && <section className="paper-accounting-card"><h2>Outstanding execution</h2>
      {report.outstanding_execution.map((attempt)=><p key={attempt.intent_id}>{attempt.state.replaceAll("_"," ")}{attempt.failure_reason ? `: ${attempt.failure_reason}` : ""} · Review this order in Quant.</p>)}
      {report.open_orders.length>0 && <div className="paper-accounting-table"><table><thead><tr><th>Symbol</th><th>Side</th><th>Remaining shares</th><th>Limit price</th></tr></thead><tbody>{report.open_orders.map((order)=><tr key={order.client_order_id}><td>{order.symbol}</td><td>{order.side}</td><td>{order.remaining_quantity}</td><td>{money(order.maximum_price_usd)}</td></tr>)}</tbody></table></div>}
    </section>}
    {!!report.protective_orders?.length && <section className="paper-accounting-card" aria-label="Protective order history"><h2>Protective orders</h2>
      <p>Broker-observed children of approved entries, including completed parents. Status timestamps can follow the account valuation. FIFO ownership of sold lots remains separate from who placed the parent order.</p>
      <div className="paper-accounting-table"><table><thead><tr><th>Symbol / role</th><th>Parent placed by</th><th>Status</th><th>Filled / unfilled</th><th>Stop / limit</th><th>Observed</th></tr></thead><tbody>{report.protective_orders.map(leg=><tr key={leg.broker_order_id}><th scope="row">{leg.symbol} · {leg.protection_role.replaceAll("_"," ")}</th><td title={leg.parent_broker_order_id}>{ownerName(leg.executor)}</td><td>{leg.status.replaceAll("_"," ")}{!leg.approved_terms_match?" · terms changed":""}</td><td>{leg.filled_quantity} / {leg.remaining_quantity}</td><td>{money(leg.stop_price_usd)} / {money(leg.limit_price_usd)}</td><td>{date(leg.observed_at)}</td></tr>)}</tbody></table></div>
    </section>}
    <section className="paper-accounting-card"><h2>Observed fills ({report.fills.length})</h2>{report.fills.length ? <div className="paper-accounting-table"><table><thead><tr><th>Executed</th><th>Symbol</th><th>Side</th><th>Quantity</th><th>Price</th><th>Placed by</th></tr></thead><tbody>{report.fills.slice(-100).reverse().map((fill)=><tr key={fill.source_id}><td>{date(fill.effective_at)}</td><td>{fill.symbol}</td><td>{fill.side}</td><td>{fill.quantity}</td><td>{money(fill.price_usd)}</td><td title={fill.parent_broker_order_id??fill.broker_order_id}>{ownerName(fill.executor)}{fill.protection_role?` · ${fill.protection_role.replaceAll("_"," ")}`:""}</td></tr>)}</tbody></table></div> : <p>No observed fills yet.</p>}{report.fills.length>100 && <p>Showing the latest 100 fills; all source activities remain in the ledger.</p>}</section>
  </>;
}

function EquityHistory({points}:{points:AccountingPoint[]}) {
  if(points.length<2) return <p>One observation is saved. A chart will appear after another reconciliation.</p>;
  const sampled=points.filter((_,i)=>i===points.length-1 || i%Math.max(1,Math.ceil(points.length/500))===0);
  const values=sampled.map((p)=>Number(p.equity_usd));
  const low=Math.min(...values), high=Math.max(...values), range=high-low || 1;
  const first=Date.parse(sampled[0].observed_at), last=Date.parse(sampled[sampled.length-1].observed_at);
  const coords=sampled.map((p,i)=>({x:20+(Date.parse(p.observed_at)-first)/Math.max(1,last-first)*660,y:180-(values[i]-low)/range*150,point:p}));
  return <><svg viewBox="0 0 700 210" role="img" aria-label={`Observed account equity from ${money(sampled[0].equity_usd)} to ${money(sampled[sampled.length-1].equity_usd)}`} className="paper-equity-chart"><line x1="20" y1="180" x2="680" y2="180" stroke="currentColor" opacity=".2"/><polyline points={coords.map((p)=>`${p.x},${p.y}`).join(" ")} fill="none" stroke="currentColor" strokeWidth="2"/>{coords.length<=50 && coords.map((p)=><circle key={p.point.observed_at} cx={p.x} cy={p.y} r="3" fill="currentColor"><title>{date(p.point.observed_at)}: {money(p.point.equity_usd)}</title></circle>)}</svg><p className="muted">{date(sampled[0].observed_at)} — {date(sampled[sampled.length-1].observed_at)} · {points.length} saved observations · range {money(String(low))}–{money(String(high))}</p></>;
}
