type SourceAge = { precision: string; age_hours: number | null };
export type ReviewManifest = {
  version: number; frozen_at: string;
  sources: { source_id: string; kind: string; sha256: string; published: SourceAge; retrieved: SourceAge; data_as_of: string | null; origin: string }[];
  coverage: { category: string; present: boolean }[]; limitations: string[];
};
export type PriceIndicators = { cutoff: string; last_close_usd: number; sma_20_usd: number; sma_50_usd: number; return_20_sessions_pct: number; realized_volatility_20_pct: number; method: string };

const fixed = (value: number) => Number.isFinite(value) ? value.toFixed(2) : "Unavailable";
const age = (value: SourceAge) => value.age_hours === null ? value.precision === "date_only" ? "Date only" : "Unknown" : `${fixed(value.age_hours)} hours before review`;

export function EvidenceReviewCards({ review, sources, briefId }: {
  review: ReviewManifest; sources: { source_id: string; title: string; indicators?: PriceIndicators }[]; briefId: string;
}) {
  const price = sources.find(source => source.indicators)?.indicators;
  const groups = new Map<string, string[]>();
  for (const source of review.sources) groups.set(source.origin, [...(groups.get(source.origin) ?? []), source.source_id]);
  const shared = [...groups.values()].filter(group => group.length > 1);
  return <section className="evidence-review" aria-label="Evidence available for this review">
    <h4>Evidence available for this review</h4>
    <p>Frozen {new Date(review.frozen_at).toLocaleString()}. These checks describe the saved inputs; they do not rate investment quality.</p>
    <div className="evidence-coverage">{review.coverage.map(item => <div key={item.category}>
      <strong>{item.category}</strong><span>{item.present ? "Included" : "Missing from this review"}</span>
    </div>)}</div>
    {price ? <section aria-label="Calculated historical indicators"><h4>Calculated from saved prices</h4>
      <p>Through {price.cutoff} · split-adjusted USD closes</p>
      <dl className="evidence-indicators">
        <div><dt>Last close</dt><dd>${fixed(price.last_close_usd)}</dd></div>
        <div><dt>20-session average</dt><dd>${fixed(price.sma_20_usd)}</dd></div>
        <div><dt>50-session average</dt><dd>${fixed(price.sma_50_usd)}</dd></div>
        <div><dt>20-session price return</dt><dd>{fixed(price.return_20_sessions_pct)}%</dd></div>
        <div><dt>Realized volatility · annualized</dt><dd>{fixed(price.realized_volatility_20_pct)}%</dd></div>
      </dl><details><summary>Calculation method</summary><p>{price.method}</p></details>
    </section> : null}
    {shared.length ? <p>Shared underlying evidence: {shared.map(group => group.map(id => sources.find(s => s.source_id === id)?.title ?? id).join(" + ")).join("; ")}. Agreement between these items is not independent confirmation.</p> : null}
    <details><summary>Source dates and fingerprints</summary><div className="evidence-table-scroll"><table>
      <caption>Source ages when the review was frozen</caption><thead><tr><th>Source</th><th>Published / observed</th><th>Retrieved</th><th>Data through</th></tr></thead>
      <tbody>{review.sources.map(source => <tr key={source.source_id}>
        <td><a href={`#${briefId}-${source.source_id}`}>{sources.find(s => s.source_id === source.source_id)?.title ?? source.source_id}</a><details><summary>SHA-256</summary>{source.sha256}</details></td>
        <td>{age(source.published)}</td><td>{age(source.retrieved)}</td><td>{source.data_as_of ?? "See source dates"}</td>
      </tr>)}</tbody>
    </table></div><ul>{review.limitations.map(item => <li key={item}>{item}</li>)}</ul></details>
  </section>;
}
