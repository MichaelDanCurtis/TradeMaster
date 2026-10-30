"use client";

import { useEffect, useState } from "react";
import { apiBase } from "@/lib/api";
import { ExplorerBriefPanel } from "@/components/ExplorerBriefPanel";
import { explorerLenses, filterExplorer, sourceLabel, type ExplorerCatalog, type ExplorerLens } from "@/lib/research-explorer";
import type { WatchlistItem } from "@/lib/types";
import "./ResearchExplorer.css";

const dateLabel = (value: string | null) => value && Number.isFinite(Date.parse(value)) ? new Date(value).toLocaleString() : "Not supplied";
const numberLabel = (value: number | null, digits = 2) => value === null ? "Unavailable" : value.toLocaleString("en-US", { maximumFractionDigits: digits });

export function ResearchExplorer({ watchlistItems, onAddToWatchlist, onResearch }: {
  watchlistItems: WatchlistItem[]; onAddToWatchlist?: (symbol: string) => void; onResearch: (symbol: string) => void;
}) {
  const [data, setData] = useState<ExplorerCatalog | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const [lens, setLens] = useState<ExplorerLens>("all");
  const [query, setQuery] = useState("");
  const [minPrice, setMinPrice] = useState(5);
  const [includeUnknown, setIncludeUnknown] = useState(true);
  const [savedOnly, setSavedOnly] = useState(false);
  const [notice, setNotice] = useState("");
  const [briefSelection, setBriefSelection] = useState<{ symbol: string; revision: number } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      setLoading(true); setError("");
      try {
        const response = await fetch(`${apiBase()}/api/discover/explorer`, { signal: controller.signal, cache: "no-store" });
        if (!response.ok) {
          const body = await response.json().catch(() => null);
          throw new Error(typeof body?.detail === "string" ? body.detail : `Explorer unavailable (${response.status})`);
        }
        const result = await response.json() as ExplorerCatalog;
        if (!controller.signal.aborted) setData(result);
      } catch (caught) {
        if (!controller.signal.aborted) setError(caught instanceof Error ? caught.message : "Unable to load candidates");
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => controller.abort();
  }, [revision]);

  const watched = new Set(watchlistItems.map((row) => row.symbol));
  const candidates = filterExplorer(data?.candidates ?? [], { lens, query, minPrice, includeUnknown, savedOnly, watched });
  const activeLens = explorerLenses.find((item) => item.id === lens)!;

  return <section className="research-explorer" aria-label="Research explorer">
    <header className="explorer-heading">
      <div><span className="panel-kicker">Discovery desk</span><h1>Find your next research idea</h1>
        <p>Explore market activity, follow the evidence, and build a watchlist worth investigating.</p></div>
      <button type="button" className="primary-button" disabled={loading} onClick={() => setRevision((value) => value + 1)}>{loading ? "Reading market sources…" : "Refresh candidates"}</button>
    </header>
    <div className="explorer-lenses" role="group" aria-label="Research paths">{explorerLenses.map((item) => <button type="button" key={item.id} aria-pressed={lens === item.id} onClick={() => setLens(item.id)}>
      <strong>{item.title}</strong><span>{item.description}</span>
    </button>)}</div>
    <div className="explorer-evidence">
      <strong>Observations first</strong><p>{activeLens.question}</p>
      <p>These are research leads. Price moves and trading activity do not establish investment value. This screen does not assign AI buy ratings.</p>
    </div>
    {error ? <p role="alert" className="explorer-error">{error}. {data ? "The previous results remain below; their observation times have not changed." : "Check the Alpaca market-data connection in Settings, then refresh."}</p> : null}
    {data ? <details className="explorer-source-status" open={data.sources.some((source) => source.status !== "available")}>
      <summary>{data.provider} · {data.sources.filter((source) => source.status === "available").length} of {data.sources.length} sources read · Retrieved {dateLabel(data.observed_at)}</summary>
      <p>A retrieval time is when we read the source. Its market update can be older, especially outside market hours. This is a bounded screener sample, not the entire stock market.</p>
      {data.sources.map((source) => <p key={source.source}><strong>{source.source === "movers" ? "Gainers and decliners" : "Most active"}: {source.status}</strong> · Provider updated {dateLabel(source.provider_updated_at)}{source.message ? ` · ${source.message}` : ""}</p>)}
    </details> : null}
    <ExplorerBriefPanel selection={briefSelection} />
    <div className="explorer-filters">
      <label>Find a ticker in these results<input type="search" value={query} placeholder="e.g. NVDA" onChange={(event) => setQuery(event.target.value)} /></label>
      <label>Minimum reported price<select value={minPrice} onChange={(event) => setMinPrice(Number(event.target.value))}><option value={0}>Any price</option><option value={5}>$5</option><option value={10}>$10</option><option value={25}>$25</option></select></label>
      <label className="explorer-checkbox"><input type="checkbox" checked={includeUnknown} onChange={(event) => setIncludeUnknown(event.target.checked)} />Include missing prices</label>
      <label className="explorer-checkbox"><input type="checkbox" checked={savedOnly} onChange={(event) => setSavedOnly(event.target.checked)} />On my watchlist</label>
    </div>
    <p role="status" aria-live="polite">{loading ? "Reading up to 25 gainers, 25 decliners and 25 most-active stocks…" : `${candidates.length} matching candidates from ${data?.candidates.length ?? 0} observed symbols.`} {notice}</p>
    {!loading && data && candidates.length === 0 ? <div className="explorer-evidence"><h2>No matching candidates</h2><p>{data.sources.every((source) => source.status !== "available") ? "Both market sources are unavailable. Check the connection and retry." : "Try another research path, lower the price threshold, include missing prices, or clear the ticker and watchlist filters."}</p></div> : null}
    <div className="explorer-results">{candidates.map((row) => <article className="explorer-card" key={row.symbol} aria-label={`${row.symbol} research candidate`}>
      <header><h2>{row.symbol}</h2>{watched.has(row.symbol) ? <span className="strategy-badge">Watching</span> : null}</header>
      <div className="explorer-tags">{row.sources.map((source) => <span key={source}>{sourceLabel(source)}</span>)}</div>
      <dl><div><dt>Reported price</dt><dd>{row.price === null ? "Unavailable" : `$${numberLabel(row.price)}`}</dd></div><div><dt>Provider change</dt><dd>{row.change_pct === null ? "Unavailable" : `${row.change_pct > 0 ? "+" : ""}${numberLabel(row.change_pct)}%`}</dd></div><div><dt>Share volume</dt><dd>{numberLabel(row.volume, 0)}</dd></div></dl>
      <p className="explorer-reason">Appears in Alpaca’s {row.sources.map(sourceLabel).join(" and ").toLowerCase()} list{row.sources.length > 1 ? "s" : ""}.</p>
      <details><summary>What to investigate</summary>
        {row.sources.map((source) => <p key={source}>{explorerLenses.find((item) => item.id === source)?.question}</p>)}
        <p>Check recent filings, earnings, balance-sheet strength, valuation, spreads and current news. Verify the security type; provider lists may include funds and leveraged products.</p>
        {row.price === null ? <p>Price is missing. This candidate has not passed the minimum-price test.</p> : null}
      </details>
      <footer><button type="button" className="primary-button compact" onClick={() => setBriefSelection((current) => ({ symbol: row.symbol, revision: (current?.revision ?? 0) + 1 }))}>Brief {row.symbol}</button>
        <button type="button" className="secondary-button compact" onClick={() => onResearch(row.symbol)}>Research {row.symbol}</button>
        {onAddToWatchlist ? <button type="button" className="secondary-button compact" disabled={watched.has(row.symbol)} onClick={() => { onAddToWatchlist(row.symbol); setNotice(`${row.symbol} added to your watchlist.`); }}>{watched.has(row.symbol) ? "On watchlist" : `Watch ${row.symbol}`}</button> : null}</footer>
    </article>)}</div>
    <p className="explorer-footnote">Browse order alternates the provider’s gainers, decliners and activity rankings. Open a symbol to inspect saved research or request a new committee review using your configured research provider.</p>
  </section>;
}
