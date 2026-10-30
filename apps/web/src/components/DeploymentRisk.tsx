import type { DeploymentEvaluation, FundedPortfolioRisk } from "@/lib/deployments";

const money=(value:string|null)=>value===null?"Unavailable":Number(value).toLocaleString(undefined,{style:"currency",currency:"USD"});
const percent=(value:string|number|null)=>value===null?"Undefined":`${(Number(value)*100).toFixed(2)}%`;

export function DeploymentRisk({ evaluation }: { evaluation:DeploymentEvaluation }) {
  const funded=evaluation.payload.funded_risk;
  if(!funded)return <p>Funded quantity risk was not recorded for this older evaluation.</p>;
  const ideal=evaluation.payload.decision?.portfolio_risk;
  return <details><summary>Risk at funded quantities and observed holdings</summary>
    <p>Compare whole-share proposals with reconciled holdings at the same decision prices. Funding is the committed nominal envelope, not measured deployment equity. These estimates exclude pending orders and are not approval or loss limits.</p>
    {ideal?<p>Ideal strategy weights before rounding: {percent(ideal.invested_fraction)} invested; annualized sample volatility {percent(ideal.annualized_volatility_fraction)}.</p>:null}
    <div style={{overflowX:"auto"}}><table><caption>Quantity-based exposure at decision prices</caption><thead><tr><th>Measure</th><th>Whole-share proposal</th><th>Reconciled holdings</th></tr></thead><tbody>
      <tr><th scope="row">Valued exposure</th><td>{money(funded.proposed?.gross_exposure_usd??null)}</td><td>{money(funded.observed.gross_exposure_usd)}</td></tr>
      <tr><th scope="row">Unused nominal envelope</th><td>{money(funded.proposed?.unused_envelope_usd??null)}</td><td>{money(funded.observed.unused_envelope_usd)}</td></tr>
      <tr><th scope="row">Headroom after required reserve, before fees</th><td>{money(funded.proposed?.reserve_headroom_usd??null)}</td><td>{money(funded.observed.reserve_headroom_usd)}</td></tr>
      <tr><th scope="row">Annualized sample dollar volatility</th><td>{money(funded.proposed?.annualized_volatility_usd??null)}</td><td>{money(funded.observed.annualized_volatility_usd)}</td></tr>
    </tbody></table></div>
    {!funded.proposed?<p>No proposed portfolio was emitted for this evaluation.</p>:<RiskAllocation title="Whole-share proposal" value={funded.proposed}/>}
    <RiskAllocation title="Reconciled holdings at decision prices" value={funded.observed}/>
  </details>;
}

function RiskAllocation({ title,value }: { title:string; value:FundedPortfolioRisk }) {
  const covariance=value.covariance;
  return <details><summary>{title} · {value.status.replaceAll("_"," ")}</summary>
    <p>{value.reason}. Funding envelope: {money(value.capital_usd)}.</p>
    {value.reserve_headroom_usd!==null&&Number(value.reserve_headroom_usd)<0?<p>Exposure exceeds the envelope available after the required reserve. Exact-order checks must resolve this before new entries.</p>:null}
    <div style={{overflowX:"auto"}}><table><caption>{title}: position exposure and concentration</caption><thead><tr><th>Symbol</th><th>Shares</th><th>Exposure</th><th>Envelope share</th><th>Position limit</th><th>Share of sample variance</th></tr></thead><tbody>{value.positions.map((position)=><tr key={position.instrument_id}>
      <th scope="row">{position.symbol}</th><td>{position.quantity}</td><td>{money(position.exposure_usd)}</td><td>{percent(position.capital_fraction)}</td><td>{money(position.limit_usd)}{position.over_limit?" · Exceeded":""}</td><td>{covariance?percent(covariance.contributions[position.instrument_id]?.share_of_portfolio_variance??null):"Unavailable"}</td>
    </tr>)}</tbody></table></div>
    <ul>{value.groups.map((group)=><li key={group.group}>{group.group}: {money(group.exposure_usd)} ({percent(group.capital_fraction)} of envelope), limit {money(group.limit_usd)}{group.over_limit?" · Exceeded":""}.</li>)}</ul>
    {covariance?<p>Covariance uses {covariance.observations} aligned returns, {covariance.first_return_session} through {covariance.last_return_session}, annualized with {covariance.annualization_sessions} sessions. Computation denominator: {money(value.covariance_denominator_usd)}. Dollar volatility relative to the nominal envelope: {percent(value.capital_relative_volatility_fraction)}. Negative variance contributions describe sample hedging and can coexist with contributions above 100%.</p>:<p>Covariance needs {value.lookback_return_sessions+1} complete available closing observations. No estimate is substituted.</p>}
    <ul>{[...value.limitations,...(covariance?.limitations??[])].map((note)=><li key={note}>{note}</li>)}</ul>
  </details>;
}
