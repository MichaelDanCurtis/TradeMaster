"use client";
import type { CompanyProfile, SecurityIdentity } from "@/lib/pulse-workbench";
import { price, volume } from "@/lib/market-pulse";

const ownershipPct = (value: number | null | undefined) =>
  value == null ? "Not reported" : `${value.toFixed(2)}%`;
export function InstrumentIdentity({
  symbol,
  identity,
  company,
  loading,
}: {
  symbol: string;
  identity?: SecurityIdentity;
  company: CompanyProfile | null;
  loading: boolean;
}) {
  const name = identity?.name ?? company?.name;
  const holder = company?.holders[0];
  return (
    <div className="pulse-instrument-identity">
      <span className="pulse-eyebrow">SELECTED SECURITY · {symbol}</span>
      <h3>
        {name ?? (loading ? "Looking up company…" : "Company name unavailable")}
      </h3>
      <span>
        {[identity?.exchange, identity?.security_type, company?.sector]
          .filter(Boolean)
          .join(" · ") || "Checking security identity"}
      </span>
      {company?.description && (
        <p>
          {company.description.split(" ").slice(0, 32).join(" ")}
          {company.description.split(" ").length > 32 ? "…" : ""}
        </p>
      )}
      {holder ? (
        <p className="pulse-owner-preview">
          Largest institution in supplied records:{" "}
          <strong>{holder.name}</strong> · {ownershipPct(holder.percent)} ·
          reported {holder.reported_at}
        </p>
      ) : (
        <p className="pulse-owner-preview">
          {loading
            ? "Checking reported ownership…"
            : "No dated institutional-holder records available for this symbol."}
        </p>
      )}
    </div>
  );
}

export function PulseCompany({
  company,
  loading,
  identity,
}: {
  company: CompanyProfile | null;
  loading: boolean;
  identity?: SecurityIdentity;
}) {
  if (!company)
    return (
      <p className="pulse-placeholder" role="status">
        {loading
          ? "Reading company figures and reported shareholders…"
          : "Company details are unavailable. The security identity above is kept separate."}
      </p>
    );
  const m = company.metrics;
  const figures: [string, string][] = [
    ["Market cap", volume(m.market_cap)],
    ["Enterprise value", volume(m.enterprise_value)],
    ["Trailing P/E", price(m.trailing_pe)],
    ["Forward P/E", price(m.forward_pe)],
    ["EPS · trailing", price(m.eps)],
    ["Revenue · trailing", volume(m.revenue)],
    [
      "Profit margin",
      m.profit_margin == null ? "—" : `${(m.profit_margin * 100).toFixed(2)}%`,
    ],
    [
      "Revenue growth",
      m.revenue_growth == null
        ? "—"
        : `${(m.revenue_growth * 100).toFixed(2)}%`,
    ],
    ["Cash", volume(m.cash)],
    ["Debt", volume(m.debt)],
    ["Free cash flow", volume(m.free_cash_flow)],
    ["Employees", volume(m.employees)],
  ];
  return (
    <div className="pulse-company-tab">
      <h4>Company & control</h4>
      <dl className="pulse-company-facts">
        <div>
          <dt>Listed issuer / security</dt>
          <dd>{identity?.name ?? company.name ?? "Not verified"}</dd>
        </div>
        <div>
          <dt>Parent company</dt>
          <dd>
            {company.parent ?? "Not established by the connected sources"}
          </dd>
        </div>
        {company.fund_family && (
          <div>
            <dt>Fund family / sponsor</dt>
            <dd>{company.fund_family} · not an ownership claim</dd>
          </div>
        )}
        <div>
          <dt>Industry</dt>
          <dd>{company.industry ?? "Not reported"}</dd>
        </div>
        <div>
          <dt>Country</dt>
          <dd>{company.country ?? "Not reported"}</dd>
        </div>
      </dl>
      <p className="pulse-footnote">
        A public security can have many owners. Management, fund sponsorship and
        a large shareholding do not by themselves establish a parent company or
        voting control.
      </p>
      <div className="pulse-company-links">
        {company.website && (
          <a href={company.website} target="_blank" rel="noopener noreferrer">
            Company website ↗
          </a>
        )}
        {company.profile_url && (
          <a
            href={company.profile_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            Profile source ↗
          </a>
        )}
      </div>
      <h4>Reported ownership</h4>
      <div className="pulse-ownership-totals">
        <div>
          <span>Insiders</span>
          <strong>{ownershipPct(company.insider_percent)}</strong>
        </div>
        <div>
          <span>Institutions</span>
          <strong>{ownershipPct(company.institutional_percent)}</strong>
        </div>
      </div>
      <h5>Largest reported institutional positions</h5>
      {company.holders.length ? (
        <div className="pulse-table-scroll">
          <table className="pulse-holders-table">
            <thead>
              <tr>
                <th>Holder</th>
                <th>Shares / stake</th>
                <th>Reported</th>
              </tr>
            </thead>
            <tbody>
              {company.holders.map((holder, i) => (
                <tr key={holder.name + holder.reported_at + i}>
                  <th scope="row">{holder.name}</th>
                  <td>
                    {volume(holder.shares)}
                    <small>{ownershipPct(holder.percent)}</small>
                  </td>
                  <td>{holder.reported_at}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="pulse-footnote">
          No dated institutional positions were supplied. This does not mean
          there are no institutional owners.
        </p>
      )}
      <h5>Reported insider / beneficial-owner positions</h5>
      {company.insiders.length ? (
        <div className="pulse-insiders">
          {company.insiders.map((holder, i) => (
            <div key={holder.name + holder.holding_type + i}>
              <strong>{holder.name}</strong>
              <span>{holder.position ?? "Role not supplied"}</span>
              <span>
                {volume(holder.shares)} shares · {holder.holding_type} ·
                reported {holder.reported_at}
              </span>
            </div>
          ))}
        </div>
      ) : (
        <p className="pulse-footnote">
          No dated insider or beneficial-owner positions were supplied.
        </p>
      )}
      {company.holders_url && (
        <a
          className="pulse-source-link"
          href={company.holders_url}
          target="_blank"
          rel="noopener noreferrer"
        >
          Yahoo Finance ownership records ↗
        </a>
      )}
      <p className="pulse-footnote">
        {company.ownership_note ?? "Ownership coverage is incomplete."}
      </p>
      <h4>
        Company figures {company.currency && <span>· {company.currency}</span>}
      </h4>
      <dl className="pulse-metrics pulse-company-metrics">
        {figures.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      <p className="pulse-footnote">
        Yahoo Finance snapshot retrieved{" "}
        {new Date(company.retrieved_at).toLocaleString()}. Financial periods and
        valuation timestamps may differ; these figures are not live quotes.
      </p>
      {company.gaps.map((gap) => (
        <p className="pulse-footnote" key={gap}>
          {gap}
        </p>
      ))}
    </div>
  );
}
