"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import {
  age,
  analysisRunning,
  linkedSource,
  pct,
  price,
  rankingReady,
  sameCapture,
  tone,
  volume,
  type PulseAnalysis,
  type PulseBoard,
  type PulseExplanation,
  type PulseMover,
  type PulseProvider,
  type PulseQuote,
} from "@/lib/market-pulse";
import "./MarketPulse.css";

async function request<T>(
  path: string,
  signal: AbortSignal,
  body?: unknown,
): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    signal,
    cache: "no-store",
    ...(body
      ? {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      : {}),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(
      typeof payload.detail === "string"
        ? payload.detail
        : `Request failed (${response.status}).`,
    );
  }
  return response.json() as Promise<T>;
}
const evidenceLabel = {
  reported_event: "Reported event",
  possible_link: "Possible link",
  insufficient: "No clear catalyst",
};
const dateTime = (value: string | null | undefined) =>
  value
    ? new Date(value).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })
    : "Timestamp unavailable";

export function MarketPulse({
  onOpenResearch,
  onOpenSettings,
  onAddToWatchlist,
}: {
  onOpenResearch: (symbol: string) => void;
  onOpenSettings: () => void;
  onAddToWatchlist?: (symbol: string) => void;
}) {
  const [board, setBoard] = useState<PulseBoard | null>(null);
  const [provider, setProvider] = useState<PulseProvider | null>(null);
  const [analysis, setAnalysis] = useState<PulseAnalysis | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [automatic, setAutomatic] = useState(true);
  const [expanded, setExpanded] = useState(false);
  const [error, setError] = useState("");
  const [aiError, setAiError] = useState("");
  const [watched, setWatched] = useState<string | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const snapshotRequest = useRef<AbortController | null>(null);
  const submitRequest = useRef<AbortController | null>(null);
  const refresh = useCallback(async (manual = false) => {
    if (snapshotRequest.current) return;
    const controller = new AbortController();
    snapshotRequest.current = controller;
    setLoading(true);
    try {
      const value = await request<PulseBoard>(
        `/api/market-pulse/snapshot?refresh=${manual}`,
        controller.signal,
      );
      if (!controller.signal.aborted) {
        setBoard(value);
        setError("");
      }
    } catch (caught) {
      if (!controller.signal.aborted)
        setError(
          caught instanceof Error
            ? caught.message
            : "Market data could not be refreshed.",
        );
    } finally {
      if (snapshotRequest.current === controller)
        snapshotRequest.current = null;
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
    const controller = new AbortController();
    // Independent requests: a missing AI provider must not hide the market board.
    void request<PulseProvider>(
      "/api/discover/briefs/status",
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setProvider(value);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setProvider({
            available: false,
            message:
              "The research provider could not be checked. Reopen this view after connecting the server.",
          });
      });
    void request<{ analysis: PulseAnalysis | null }>(
      "/api/market-pulse/analysis",
      controller.signal,
    )
      .then((value) => {
        if (!controller.signal.aborted) setAnalysis(value.analysis);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setAiError(
            "Saved explanations could not be loaded. Reopen this view to recover them.",
          );
      });
    const clock = window.setInterval(() => setNow(Date.now()), 15_000);
    return () => {
      controller.abort();
      snapshotRequest.current?.abort();
      snapshotRequest.current = null;
      submitRequest.current?.abort();
      window.clearInterval(clock);
    };
  }, [refresh]);

  useEffect(() => {
    if (!automatic) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) void refresh();
    }, 60_000);
    return () => window.clearInterval(timer);
  }, [automatic, refresh]);

  const running = analysisRunning(analysis);
  const identifier = analysis?.brief_id;
  useEffect(() => {
    if (!running || !identifier) return;
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const result = await request<PulseAnalysis>(
          `/api/market-pulse/analysis/${identifier}`,
          controller.signal,
        );
        if (!controller.signal.aborted) {
          setAnalysis(result);
          setAiError("");
        }
      } catch {
        if (!controller.signal.aborted)
          setAiError(
            "Connection interrupted. Checking this same analysis again; no new AI call is being started.",
          );
      }
      if (!controller.signal.aborted) timer = setTimeout(poll, 2000);
    }
    timer = setTimeout(poll, 1000);
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [identifier, running]);

  async function explain() {
    if (!board || !provider?.provider_config_hash || submitRequest.current)
      return;
    const controller = new AbortController();
    submitRequest.current = controller;
    setStarting(true);
    setAiError("");
    try {
      const result = await request<PulseAnalysis>(
        "/api/market-pulse/analysis",
        controller.signal,
        {
          snapshot_id: board.snapshot_id,
          provider_config_hash: provider.provider_config_hash,
        },
      );
      if (!controller.signal.aborted) setAnalysis(result);
    } catch (caught) {
      if (!controller.signal.aborted)
        setAiError(
          caught instanceof Error
            ? caught.message
            : "Analysis could not be started.",
        );
    } finally {
      if (submitRequest.current === controller) submitRequest.current = null;
      if (!controller.signal.aborted) setStarting(false);
    }
  }

  const movers = board ? [...board.gainers, ...board.losers] : [];
  const symbol = selected ?? movers[0]?.symbol ?? null;
  const mover = movers.find((row) => row.symbol === symbol);
  const explanation =
    analysis?.state === "completed"
      ? analysis.receipt?.proposal?.explanations.find(
          (row) => row.symbol === symbol,
        )
      : undefined;
  const matched = sameCapture(board, analysis);
  const count = board
    ? Math.min(5, board.gainers.length) + Math.min(5, board.losers.length)
    : 0;
  const sectors = board?.sectors.filter((row) => row.change_pct != null) ?? [];
  const positiveSectors = sectors.filter(
    (row) => (row.change_pct ?? 0) > 0,
  ).length;
  const ranksAt = board?.sources.find(
    (source) => source.source === "movers",
  )?.updated_at;
  const disabledReason = !provider?.available
    ? "Connect a Codex research provider in Settings."
    : !rankingReady(board, now)
      ? "Refresh valid, timestamped market movers before requesting analysis."
      : matched
        ? "This capture already has an assessment attempt. Refresh market data for a new assessment."
        : "";

  return (
    <section className="pulse" aria-label="Market Pulse">
      <header className="pulse-toolbar">
        <div>
          <span className="pulse-eyebrow">THE MARKET, AT A GLANCE</span>
          <h1>
            Market Pulse
            <span className="pulse-dot" />
          </h1>
        </div>
        <div className="pulse-controls">
          <span
            className={`pulse-health ${error || board?.status === "unavailable" ? "down" : "neutral"}`}
          >
            {error
              ? "Refresh failed"
              : loading
                ? "Updating…"
                : board?.status === "available"
                  ? "Sources responding"
                  : board?.status === "partial"
                    ? "Partial coverage"
                    : "Data unavailable"}
          </span>
          <label>
            <input
              type="checkbox"
              checked={automatic}
              onChange={(event) => setAutomatic(event.target.checked)}
            />
            Auto · 60s
          </label>
          <button
            type="button"
            onClick={() => void refresh(true)}
            disabled={loading}
          >
            {loading ? "Refreshing…" : "↻ Refresh"}
          </button>
          <button
            type="button"
            className="pulse-icon-button"
            onClick={onOpenSettings}
          >
            Connections
          </button>
        </div>
      </header>
      {error && (
        <p className="pulse-alert" role="alert">
          {error}{" "}
          {board
            ? "Showing the previous capture; timestamps below have not changed."
            : "Check that the local API is running."}
        </p>
      )}
      {board?.status === "unavailable" && (
        <div className="pulse-empty-connect">
          <strong>Connect market data to light up your desk.</strong>
          <span>
            Configure Alpaca market data in Settings. Rankings need screener
            access; snapshots use your selected feed. Missing data stays blank.
          </span>
          <button type="button" onClick={onOpenSettings}>
            Open connections →
          </button>
        </div>
      )}
      <div
        className="pulse-benchmarks"
        aria-label="Index and asset ETF proxies"
      >
        {(board?.benchmarks ?? []).map((row) => (
          <button
            type="button"
            className="pulse-benchmark"
            key={row.symbol}
            onClick={() => onOpenResearch(row.symbol)}
            title={`${row.label} ETF proxy · ${dateTime(row.price_at)}`}
          >
            <span className="pulse-tile-heading">
              <b>{row.symbol}</b>
              <span>{row.label}</span>
            </span>
            <span className="pulse-tile-price">
              {price(row.price)}{" "}
              <b className={tone(row.change_pct)}>{pct(row.change_pct)}</b>
            </span>
            <span className="pulse-tile-time">
              {age(row.price_at, now)}
              <span>ETF proxy</span>
            </span>
          </button>
        ))}
        {!board && (
          <p className="pulse-placeholder">
            {loading
              ? "Loading index and sector snapshots…"
              : "No market snapshot available."}
          </p>
        )}
      </div>
      <div className="pulse-body">
        <div className="pulse-market-column">
          <section
            className="pulse-panel pulse-sector-panel"
            aria-label="Sector ETF performance"
          >
            <div className="pulse-panel-heading">
              <h2>
                Sector map <span>11 ETF proxies</span>
              </h2>
              <span>
                {positiveSectors}/{sectors.length} reporting ETFs up
              </span>
            </div>
            <div className="pulse-sector-grid">
              {board?.sectors.map((row) => (
                <button
                  type="button"
                  key={row.symbol}
                  onClick={() => onOpenResearch(row.symbol)}
                  className={`pulse-sector ${tone(row.change_pct)}`}
                  style={{
                    backgroundColor:
                      row.change_pct == null
                        ? undefined
                        : `rgba(${row.change_pct >= 0 ? "38,166,154" : "239,83,80"},${Math.min(0.35, 0.07 + Math.abs(row.change_pct) * 0.06)})`,
                  }}
                  title={`${row.label} · ${dateTime(row.price_at)}`}
                >
                  <b>{row.symbol}</b>
                  <strong>{pct(row.change_pct)}</strong>
                  <span>{row.label}</span>
                </button>
              ))}
            </div>
          </section>
          <section className="pulse-panel" aria-label="Market movers">
            <div className="pulse-panel-heading">
              <h2>
                Market movers <span>SIP rankings</span>
              </h2>
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
              >
                {expanded ? "Show top 5 each" : "Show up to 25 each"}
              </button>
            </div>
            <div className="pulse-movers">
              <MoversTable
                title="Gainers"
                rows={(board?.gainers ?? []).slice(0, expanded ? 25 : 5)}
                symbol={symbol}
                onSelect={setSelected}
                now={now}
                analysis={analysis}
                matched={matched}
              />
              <MoversTable
                title="Losers"
                rows={(board?.losers ?? []).slice(0, expanded ? 25 : 5)}
                symbol={symbol}
                onSelect={setSelected}
                now={now}
                analysis={analysis}
                matched={matched}
              />
            </div>
            <p className="pulse-footnote">
              Rankings:{" "}
              <time title={dateTime(ranksAt)}>{age(ranksAt, now)}</time>.{" "}
              {board?.ranking_basis ?? "Waiting for provider-ranked movers."}{" "}
              Select a ticker for its evidence.
            </p>
          </section>
          <section className="pulse-panel" aria-label="Most active stocks">
            <div className="pulse-panel-heading">
              <h2>
                Volume leaders{" "}
                <span>
                  SIP activity · {board?.feed.toUpperCase() ?? "—"} prices
                </span>
              </h2>
              <span
                title={dateTime(
                  board?.sources.find((s) => s.source === "activity")
                    ?.updated_at,
                )}
              >
                {age(
                  board?.sources.find((s) => s.source === "activity")
                    ?.updated_at,
                  now,
                )}
              </span>
            </div>
            <div className="pulse-activity">
              {board?.activity.slice(0, 10).map((row) => (
                <button
                  type="button"
                  key={row.symbol}
                  onClick={() => onOpenResearch(row.symbol)}
                  title={`Price: ${dateTime(row.price_at)}`}
                >
                  <b>{row.symbol}</b>
                  <span>{price(row.price)}</span>
                  <span className={tone(row.change_pct)}>
                    {pct(row.change_pct)}
                  </span>
                  <span>{volume(row.screener_volume)} sh</span>
                </button>
              ))}
              {!board?.activity.length && (
                <p className="pulse-placeholder">
                  No activity ranking available.
                </p>
              )}
            </div>
          </section>
          <footer className="pulse-provenance">
            <span>{board?.snapshot_basis}</span>
            <span>{board?.coverage}</span>
            <span>
              Capture: {dateTime(board?.captured_at)} · Retrieval time is not
              quote time.
            </span>
          </footer>
        </div>
        <aside
          className="pulse-panel pulse-intelligence"
          aria-label="Why stocks are moving"
        >
          <div className="pulse-intelligence-header">
            <span className="pulse-eyebrow">CATALYST DESK</span>
            <h2>
              Behind the move<span>✦</span>
            </h2>
            <p>Possible causes, grounded in dated news.</p>
          </div>
          <div className="pulse-ai-action">
            <button
              type="button"
              className="pulse-primary"
              disabled={!!disabledReason || starting || running}
              title={disabledReason}
              onClick={() => void explain()}
            >
              {starting
                ? "Starting…"
                : running
                  ? "Reading the evidence…"
                  : `✦ Explain top ${count || 10}`}
            </button>
            <span>
              One Codex assessment · top 5 gainers + top 5 losers
              <br />
              Automatic refresh updates prices only. News uses{" "}
              {board?.news_provider === "alpaca" ? "Alpaca" : "Finnhub"}.
            </span>
            {!provider?.available && (
              <button
                type="button"
                className="pulse-text-button"
                onClick={onOpenSettings}
              >
                {provider
                  ? "Connect Codex in Settings →"
                  : "Checking Codex connection…"}
              </button>
            )}
            {provider?.available && (
              <span>
                Model: {provider.model_id} · uses subscription allowance
              </span>
            )}
            {provider?.available && !rankingReady(board, now) && (
              <span>Waiting for valid, dated mover rankings.</span>
            )}
            {aiError && (
              <p className="pulse-alert" role="alert">
                {aiError}
              </p>
            )}
          </div>
          {analysis && (
            <div className="pulse-analysis-status" role="status">
              <b>
                {running
                  ? "Assessment in progress"
                  : analysis.state === "completed"
                    ? "Assessment saved"
                    : analysis.state.replaceAll("_", " ")}
              </b>
              <span>
                {matched
                  ? "Matches this capture"
                  : "Earlier capture — prices may have changed"}{" "}
                · {dateTime(analysis.packet?.collected_at)}
              </span>
              {analysis.state !== "completed" && <p>{analysis.message}</p>}
            </div>
          )}
          {symbol ? (
            <div className="pulse-detail">
              <div className="pulse-detail-symbol">
                <h3>{symbol}</h3>
                {mover && (
                  <div>
                    <strong className={tone(mover.change_pct)}>
                      {pct(mover.change_pct)}
                    </strong>
                    <span>${price(mover.price)} · ranked price</span>
                  </div>
                )}
              </div>
              {mover && (
                <QuoteMetrics
                  row={mover.snapshot}
                  feed={board?.feed ?? ""}
                  now={now}
                />
              )}
              {explanation && analysis ? (
                <Explanation
                  item={explanation}
                  analysis={analysis}
                  symbol={symbol}
                  matched={matched}
                />
              ) : (
                <div className="pulse-unexplained">
                  <span className="pulse-outline-symbol">?</span>
                  <h4>
                    {running
                      ? "Checking news and alternative explanations"
                      : "A price move is only half the story."}
                  </h4>
                  <p>
                    {analysis?.state === "insufficient_evidence"
                      ? "No usable company news was returned. No AI call was made and no cause has been assigned."
                      : analysis?.state === "completed"
                        ? "This ticker was not explained in the saved assessment. Refresh and explain the current top movers to investigate."
                        : "Ask Codex to review the top movers together. It will connect relevant headlines, identify uncertainty, and show the evidence behind each explanation."}
                  </p>
                </div>
              )}
              <div className="pulse-detail-actions">
                <button type="button" onClick={() => onOpenResearch(symbol)}>
                  Research {symbol} ↗
                </button>
                {onAddToWatchlist && (
                  <button
                    type="button"
                    onClick={() => {
                      onAddToWatchlist(symbol);
                      setWatched(symbol);
                    }}
                  >
                    {watched === symbol ? "✓ In watchlist" : "+ Watchlist"}
                  </button>
                )}
              </div>
              {analysis?.packet?.gaps
                .filter((gap) => gap.startsWith(symbol + ":"))
                .map((gap) => (
                  <p className="pulse-footnote" key={gap}>
                    {gap}
                  </p>
                ))}
            </div>
          ) : (
            <p className="pulse-placeholder">
              The first available mover will appear here.
            </p>
          )}
          <p className="pulse-caveat">
            News timing can suggest a connection; it does not prove causation.
            Only linked headlines and summaries are read. This view does not
            place trades.
          </p>
        </aside>
      </div>
    </section>
  );
}

function MoversTable({
  title,
  rows,
  symbol,
  onSelect,
  now,
  analysis,
  matched,
}: {
  title: string;
  rows: PulseMover[];
  symbol: string | null;
  onSelect: (symbol: string) => void;
  now: number;
  analysis: PulseAnalysis | null;
  matched: boolean;
}) {
  return (
    <div className="pulse-mover-group">
      <h3>
        <span className={title === "Gainers" ? "up" : "down"}>
          {title === "Gainers" ? "↗" : "↘"} {title}
        </span>
        <span>{rows.length} symbols</span>
      </h3>
      <div className="pulse-table-scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Ticker</th>
              <th scope="col">Price</th>
              <th scope="col">Change</th>
              <th
                scope="col"
                title="Day volume from the configured snapshot feed"
              >
                Day vol.
              </th>
              <th scope="col">Catalyst</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const explanation =
                analysis?.state === "completed" && matched
                  ? analysis.receipt?.proposal?.explanations.find(
                      (item) => item.symbol === row.symbol,
                    )
                  : undefined;
              return (
                <tr
                  key={row.symbol}
                  className={symbol === row.symbol ? "selected" : ""}
                >
                  <th scope="row">
                    <button
                      type="button"
                      onClick={() => onSelect(row.symbol)}
                      aria-pressed={symbol === row.symbol}
                      aria-label={`Inspect ${row.symbol}`}
                    >
                      <span className="pulse-rank">{i + 1}</span>
                      {row.symbol}
                    </button>
                  </th>
                  <td title={dateTime(row.as_of)}>{price(row.price)}</td>
                  <td className={tone(row.change_pct)}>
                    {pct(row.change_pct)}
                  </td>
                  <td
                    title={`Snapshot day: ${dateTime(row.snapshot.day_at)} · price ${age(row.snapshot.price_at, now)}`}
                  >
                    {volume(row.snapshot.volume)}
                  </td>
                  <td>
                    <button
                      type="button"
                      className={`pulse-catalyst ${explanation && explanation.evidence !== "insufficient" ? "identified" : ""}`}
                      onClick={() => onSelect(row.symbol)}
                    >
                      {explanation
                        ? explanation.driver === "unclear"
                          ? "Unclear"
                          : explanation.driver.replaceAll("_", " ")
                        : "Inspect →"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {!rows.length && (
        <p className="pulse-placeholder">
          No ranked {title.toLowerCase()} available.
        </p>
      )}
    </div>
  );
}
function QuoteMetrics({
  row,
  feed,
  now,
}: {
  row: PulseQuote;
  feed: string;
  now: number;
}) {
  return (
    <div className="pulse-quote-context">
      <span>
        {feed.toUpperCase()} supplemental snapshot · {age(row.price_at, now)}
      </span>
      <dl className="pulse-metrics">
        <div>
          <dt>Day range</dt>
          <dd>
            {price(row.low)} — {price(row.high)}
          </dd>
        </div>
        <div>
          <dt>Day volume</dt>
          <dd>{volume(row.volume)}</dd>
        </div>
        <div>
          <dt>Open gap</dt>
          <dd className={tone(row.gap_pct)}>{pct(row.gap_pct)}</dd>
        </div>
        <div>
          <dt>Vs. day VWAP</dt>
          <dd className={tone(row.vwap_delta_pct)}>
            {pct(row.vwap_delta_pct)}
          </dd>
        </div>
        <div>
          <dt>Spread</dt>
          <dd title={dateTime(row.quote_at)}>
            {row.spread_bps == null ? "—" : `${row.spread_bps.toFixed(1)} bps`}
          </dd>
        </div>
        <div>
          <dt>Snapshot price</dt>
          <dd>{price(row.price)}</dd>
        </div>
      </dl>
    </div>
  );
}
function Explanation({
  item,
  analysis,
  symbol,
  matched,
}: {
  item: PulseExplanation;
  analysis: PulseAnalysis;
  symbol: string;
  matched: boolean;
}) {
  const preserved = analysis.packet?.movers.find(
    (row) => row.symbol === symbol,
  );
  return (
    <article className="pulse-explanation">
      {!matched && (
        <p className="pulse-prior">
          Saved assessment for {symbol} {pct(preserved?.change_pct)} at{" "}
          {dateTime(preserved?.as_of)}. It has not been rechecked against the
          current ranking.
        </p>
      )}
      <span className={`pulse-evidence-label ${item.evidence}`}>
        {evidenceLabel[item.evidence]}
        {item.driver !== "unclear"
          ? ` · ${item.driver.replaceAll("_", " ")}`
          : ""}
      </span>
      <p className="pulse-summary">{item.summary}</p>
      <h4>What else could explain it?</h4>
      <p>{item.alternative}</p>
      {!!item.citations.length && <h4>Evidence trail</h4>}
      {item.citations.map((cite) => {
        const source = linkedSource(analysis, cite.source_id);
        return source ? (
          <a
            className="pulse-source"
            key={cite.source_id}
            href={source.url!}
            target="_blank"
            rel="noopener noreferrer"
          >
            <span>{source.publisher} ↗</span>
            <strong>{source.title}</strong>
            <q>{cite.quote}</q>
            <time>{dateTime(source.published_at)}</time>
          </a>
        ) : null;
      })}
    </article>
  );
}
