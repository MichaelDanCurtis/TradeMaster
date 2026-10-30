"use client";

import { useEffect, useRef, useState } from "react";
import { apiBase } from "@/lib/api";
import { EvidenceReviewCards, type ReviewManifest, type PriceIndicators } from "./EvidenceReviewCards";
import { EvidenceAttachments, type Attachment } from "./EvidenceAttachments";

type Source = { source_id: string; title: string; publisher: string; published_at: string | null; retrieved_at: string; url: string | null; kind: string; text: string; indicators?: PriceIndicators; attachment_id?: string; page?: number; image_sha256?: string; declared_date?: string | null };
type Claim = { text: string; kind: "observation" | "inference"; citations: { source_id: string; quote: string | null; region?: string | null }[] };
type Proposal = { overview: Claim; catalysts: Claim[]; bull_case: Claim[]; bear_case: Claim[]; rejection_tests: string[]; gaps: string[]; evidence_checks?: (Claim & { relationship: "agreement" | "tension" | "not_comparable" })[] };
type Brief = {
  brief_id: string; symbol: string; model_id: string; provider_id: string; state: string; created_at: string; completed_at: string | null;
  message: string; packet_hash: string | null;
  packet: { sources: Source[]; gaps: string[]; collected_at: string; scope: string; review?: ReviewManifest } | null;
  receipt: { proposal: Proposal | null; validation_errors: string[]; input_tokens: number | null; output_tokens: number | null; actual_model_id: string } | null;
};
type ProviderStatus = { available: boolean; model_id?: string; provider_config_hash?: string; message: string };
const activeStates = new Set(["queued", "collecting", "synthesizing"]);
const dateLabel = (value: string) => /^\d{4}-\d{2}-\d{2}$/.test(value) ? `${value} (date only)` : new Date(value).toLocaleString();

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `Brief request failed (${response.status})`);
  if (!body) throw new Error("No brief response received");
  return body as T;
}

function ClaimCard({ claim, sources, briefId }: { claim: Claim; sources: Source[]; briefId: string }) {
  return <div className="explorer-claim"><span className="strategy-badge">{claim.kind === "inference" ? "AI interpretation" : "AI-reported observation"}</span>
    <p>{claim.text}</p><ul>{claim.citations.map((citation, index) => {
      const source = sources.find((item) => item.source_id === citation.source_id);
      return <li key={`${citation.source_id}-${index}`}>{citation.region ? <span>Visual reference: {citation.region} (not an exact-text verification)</span> : <q>{citation.quote}</q>} — <a href={`#${briefId}-${citation.source_id}`}>{source?.title ?? citation.source_id}</a></li>;
    })}</ul></div>;
}

export function ExplorerBriefPanel({ selection }: { selection: { symbol: string; revision: number } | null }) {
  const [symbol, setSymbol] = useState("");
  const [provider, setProvider] = useState<ProviderStatus | null>(null);
  const [history, setHistory] = useState<Brief[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [revision, setRevision] = useState(0);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [preparing, setPreparing] = useState(false);
  const requestRef = useRef<{ symbol: string; hash: string; key: string; attachments: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  useEffect(() => {
    if (selection) {
      setSymbol(selection.symbol); setSelectedId(null);
      heading.current?.focus();
      heading.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, [selection]);
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function load() {
      try {
        const [status, records] = await Promise.all([
          fetch(`${apiBase()}/api/discover/briefs/status`, { signal: controller.signal, cache: "no-store" }).then(readJson<ProviderStatus>),
          fetch(`${apiBase()}/api/discover/briefs`, { signal: controller.signal, cache: "no-store" }).then(readJson<{ briefs: Brief[] }>),
        ]);
        if (controller.signal.aborted) return;
        setProvider(status); setHistory(records.briefs); setError("");
        timer = setTimeout(load, records.briefs.some((row) => activeStates.has(row.state)) ? 2500 : 30000);
      } catch (caught) {
        if (!controller.signal.aborted) {
          setError(caught instanceof Error ? caught.message : "Could not read saved briefs");
          timer = setTimeout(load, 10000);
        }
      } finally { if (!controller.signal.aborted) setLoading(false); }
    }
    void load();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [revision]);

  const selected = history.find((row) => row.brief_id === selectedId) ?? history.find((row) => row.symbol === symbol) ?? (symbol ? null : history[0]) ?? null;
  const running = history.find((row) => activeStates.has(row.state));
  const proposal = selected?.receipt?.proposal;
  const sources = selected?.packet?.sources ?? [];
  const normalized = symbol.trim().toUpperCase();
  const validSymbol = /^[A-Z][A-Z0-9.\-]{0,11}$/.test(normalized);
  const selectedAttachments = attachments.filter(item => item.symbol === normalized);

  async function createBrief() {
    if (sending || preparing || !validSymbol || !provider?.available || !provider.provider_config_hash || running) return;
    const hash = provider.provider_config_hash;
    const attachmentIds = selectedAttachments.map(item => item.id);
    const attachmentKey = JSON.stringify(attachmentIds);
    if (!requestRef.current || requestRef.current.symbol !== normalized || requestRef.current.hash !== hash || requestRef.current.attachments !== attachmentKey) {
      requestRef.current = { symbol: normalized, hash, key: crypto.randomUUID(), attachments: attachmentKey };
    }
    setSending(true); setError("");
    try {
      const row = await fetch(`${apiBase()}/api/discover/briefs`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ symbol: normalized, idempotency_key: requestRef.current.key, provider_config_hash: hash, attachment_ids: attachmentIds }),
      }).then(readJson<Brief>);
      if (!mounted.current) return;
      requestRef.current = null;
      setAttachments(current => current.filter(item => !attachmentIds.includes(item.id)));
      setSelectedId(row.brief_id); setHistory((current) => [row, ...current.filter((item) => item.brief_id !== row.brief_id)].slice(0, 10));
      setRevision((value) => value + 1);
    } catch (caught) {
      if (mounted.current) setError(`${caught instanceof Error ? caught.message : "Request not confirmed"}. Refresh saved briefs to check whether it started. Resending this request uses the same identifier.`);
    } finally { if (mounted.current) setSending(false); }
  }

  return <section className="explorer-brief-panel" aria-label="Evidence research briefs">
    <header><span className="panel-kicker">From lead to investment question</span><h2 ref={heading} tabIndex={-1}>Evidence research brief</h2>
      <p>Ask {provider?.model_id ?? "your configured Codex model"} to compare dated company evidence, news, saved price indicators and TimesFM forecasts. Review agreement, tension, missing evidence and what would rule the idea out. Indicators use saved prices; forecasts stay labeled as predictions.</p></header>
    <p className="explorer-footnote">{provider?.message ?? "Checking the configured research provider…"}</p>
    <form className="explorer-brief-form" onSubmit={(event) => { event.preventDefault(); void createBrief(); }}>
      <label>Brief ticker<input value={symbol} maxLength={12} disabled={preparing || sending} placeholder="Choose a candidate or enter a ticker" onChange={(event) => { setSymbol(event.target.value.toUpperCase()); setSelectedId(null); }} /></label>
      <button className="primary-button compact" type="submit" disabled={loading || sending || preparing || !validSymbol || !provider?.available || Boolean(running)}>{sending ? "Requesting brief…" : `Write ${normalized || "research"} brief`}</button>
      <button className="secondary-button compact" type="button" disabled={sending} onClick={() => setRevision((value) => value + 1)}>Refresh saved briefs</button>
    </form>
    <EvidenceAttachments key={normalized} symbol={normalized} selected={selectedAttachments} disabled={sending || Boolean(running)}
      onBusy={setPreparing} onAdd={item => setAttachments(current => [...current, item])} onRemove={id => setAttachments(current => current.filter(item => item.id !== id))} />
    {error ? <p role="alert" className="explorer-error">{error}</p> : null}
    {running ? <p role="status">{running.symbol}: {running.message} You can keep exploring while this runs.</p> : null}
    {history.length ? <details className="explorer-brief-history"><summary>Recent briefs ({history.length}, latest ten)</summary><ul>{history.map((row) => <li key={row.brief_id}><button type="button" className="secondary-button compact" aria-pressed={selected?.brief_id === row.brief_id} onClick={() => { setSelectedId(row.brief_id); setSymbol(row.symbol); }}>{row.symbol} · {row.state.replaceAll("_", " ")} · {dateLabel(row.created_at)}</button></li>)}</ul></details> : <p>{loading ? "Loading saved briefs…" : "No saved briefs yet. Choose a candidate to begin."}</p>}
    {selected ? <details open className="explorer-brief-result" aria-label={`${selected.symbol} saved brief`}>
      <summary>{selected.symbol} brief · {selected.state.replaceAll("_", " ")}</summary>
      <h3>{selected.symbol} · {selected.state.replaceAll("_", " ")}</h3>
      <p>{selected.message}</p><p className="explorer-footnote">Requested {dateLabel(selected.created_at)} · {selected.model_id}{selected.completed_at ? ` · Finished ${dateLabel(selected.completed_at)}` : ""}</p>
      {selected.packet?.review ? <EvidenceReviewCards review={selected.packet.review} sources={sources} briefId={selected.brief_id} /> : selected.packet ? <p>This older brief predates the structured evidence review. Its original sources and findings remain below.</p> : null}
      {proposal ? <>
        <ClaimCard claim={proposal.overview} sources={sources} briefId={selected.brief_id} />
        {selected.packet?.review ? <section aria-label="Cross-source evidence checks"><h4>How the evidence fits together</h4>
          {proposal.evidence_checks?.length ? proposal.evidence_checks.map((check, index) => <div key={index}>
            <h5>{check.relationship === "agreement" ? "Agreement" : check.relationship === "tension" ? "Tension to investigate" : "Not directly comparable"}</h5>
            <ClaimCard claim={check} sources={sources} briefId={selected.brief_id} />
          </div>) : <p>No supported comparison was returned. See the unanswered questions below.</p>}
        </section> : null}
        <div className="explorer-brief-columns">{([ ["Catalysts to investigate", proposal.catalysts], ["Bull case", proposal.bull_case], ["Bear case", proposal.bear_case] ] as [string, Claim[]][]).map(([title, claims]) => <section key={title}><h4>{title}</h4>{claims.length ? claims.map((claim, index) => <ClaimCard key={index} claim={claim} sources={sources} briefId={selected.brief_id} />) : <p>The supplied evidence does not support a case here yet.</p>}</section>)}</div>
        <h4>What would rule this idea out?</h4><ul>{proposal.rejection_tests.map((item, index) => <li key={index}>{item}</li>)}</ul>
        <h4>Questions still unanswered</h4><ul>{proposal.gaps.map((item, index) => <li key={index}>{item}</li>)}</ul>
      </> : null}
      {selected.receipt?.validation_errors.length ? <ul>{selected.receipt.validation_errors.map((item, index) => <li key={index}>{item}</li>)}</ul> : null}
      {selected.packet ? <><h4>Evidence coverage</h4><p>{selected.packet.scope}</p><ul>{selected.packet.gaps.map((gap, index) => <li key={index}>{gap}</li>)}</ul>
        <h4>Preserved sources</h4><div className="explorer-brief-sources">{sources.map((source) => <section id={`${selected.brief_id}-${source.source_id}`} key={source.source_id}>
          <h5>{source.url ? <a href={source.url} target="_blank" rel="noopener noreferrer">{source.title}</a> : source.title}</h5>
          <p>{source.publisher} · Published/observed {source.published_at ? dateLabel(source.published_at) : "Not established; see dates within the source"} · Retrieved {dateLabel(source.retrieved_at)}</p>
          {source.attachment_id ? <><p>User-declared date: {source.declared_date ?? "Unknown"} · identity and date unverified · Selected page {source.page}</p>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img className="evidence-saved-image" src={`${apiBase()}/api/discover/briefs/attachments/${source.attachment_id}/page-${source.page}.png`} alt={`${source.title}; preserved image supplied to the model`} loading="lazy" />
            <p><a href={`${apiBase()}/api/discover/briefs/attachments/${source.attachment_id}/original`}>Download preserved original</a></p><p>Image fingerprint: {source.image_sha256}</p>
          </> : null}
          <details><summary>Read preserved excerpt</summary><p className="explorer-source-excerpt">{source.text}</p></details>
        </section>)}</div></> : null}
      {selected.packet_hash ? <p><a href={`${apiBase()}/api/discover/briefs/${encodeURIComponent(selected.brief_id)}/evidence.json`}>Download evidence and review JSON</a> · <a href={`${apiBase()}/api/discover/briefs/${encodeURIComponent(selected.brief_id)}/evidence.zip`}>Download review with original attachments</a></p> : null}
      <details><summary>Brief record and usage</summary><p>Record: {selected.brief_id}</p><p>Evidence fingerprint: {selected.packet_hash ?? "Not collected"}</p><p>Input tokens: {selected.receipt?.input_tokens ?? "Unavailable"} · Output tokens: {selected.receipt?.output_tokens ?? "Unavailable"}</p><p>Subscription usage; no API dollar charge is estimated. Citation checks verify references and excerpts, not whether an interpretation is correct.</p></details>
    </details> : null}
  </section>;
}
