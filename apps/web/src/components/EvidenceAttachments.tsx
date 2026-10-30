"use client";

import { useRef, useState } from "react";
import { apiBase } from "@/lib/api";

export type Attachment = { id: string; symbol: string; manifest: {
  filename: string; page_count: number; published_on: string | null;
  pages: { page: number; width: number; height: number }[];
} };

export function EvidenceAttachments({ symbol, selected, disabled, onAdd, onRemove, onBusy }: {
  symbol: string; selected: Attachment[]; disabled: boolean;
  onAdd: (attachment: Attachment) => void; onRemove: (id: string) => void; onBusy: (busy: boolean) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [pages, setPages] = useState("1");
  const [published, setPublished] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileInput = useRef<HTMLInputElement>(null);
  const count = selected.reduce((n, item) => n + item.manifest.pages.length, 0);
  const validSymbol = /^[A-Z][A-Z0-9.\-]{0,11}$/.test(symbol);
  async function prepare() {
    if (!file || busy || disabled || !validSymbol) return;
    if (file.size > 10*1024*1024) { setError("Choose a file smaller than 10 MB."); return; }
    const selectedPages = file.name.toLowerCase().endsWith(".pdf") ? pages.replaceAll(" ", "") : "1";
    if (count + selectedPages.split(",").length > 4) { setError("Choose at most four pages/images across the attachments."); return; }
    setBusy(true); onBusy(true); setError("");
    try {
      const query = new URLSearchParams({ symbol, filename: file.name, pages: selectedPages });
      if (published) query.set("published_on", published);
      const response = await fetch(`${apiBase()}/api/discover/briefs/attachments?${query}`, {
        method: "POST", headers: { "Content-Type": "application/octet-stream" }, body: file,
      });
      const result = await response.json();
      if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : "Could not prepare this attachment.");
      onAdd(result as Attachment); setFile(null);
      if (fileInput.current) fileInput.current.value = "";
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Attachment preparation failed."); }
    finally { setBusy(false); onBusy(false); }
  }
  return <section className="evidence-upload" aria-label="Optional image and PDF evidence">
    <h3>Optional chart or PDF evidence</h3>
    <p>Choose a ticker first. Preparation stays on this computer. When you write the brief, the selected images and PDF page text are sent to your configured Codex model. Up to two files, four selected pages/images total, 10 MB per file.</p>
    <div className="explorer-brief-form">
      <label>Image or PDF<input ref={fileInput} type="file" accept="image/png,image/jpeg,application/pdf" disabled={disabled || busy || selected.length >= 2 || !validSymbol}
        onChange={event => { setFile(event.target.files?.[0] ?? null); setError(""); }} /></label>
      <label>PDF pages (for example 1,3)<input value={pages} maxLength={15} disabled={disabled || busy || !file?.name.toLowerCase().endsWith(".pdf")} onChange={event => setPages(event.target.value)} /></label>
      <label>Document date, if known<input type="date" value={published} disabled={disabled || busy} onChange={event => setPublished(event.target.value)} /></label>
      <button type="button" className="secondary-button compact" disabled={!file || busy || disabled || !validSymbol || selected.length >= 2} onClick={() => void prepare()}>{busy ? "Preparing previews…" : "Prepare attachment locally"}</button>
    </div>
    {error ? <p role="alert">{error}</p> : null}
    {selected.map(item => <article key={item.id} className="evidence-upload-item">
      <h4>{item.manifest.filename} · {item.symbol}</h4><p>Selected pages: {item.manifest.pages.map(page => page.page).join(", ")} of {item.manifest.page_count}. {item.manifest.published_on ? `User-declared date: ${item.manifest.published_on}; unverified.` : "Document date unknown."}</p>
      <div className="evidence-previews">{item.manifest.pages.map(page => <figure key={page.page}>
        {/* Local prepared images are intentionally served by the existing API. */}
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img src={`${apiBase()}/api/discover/briefs/attachments/${item.id}/page-${page.page}.png`} alt={`${item.manifest.filename}, selected page ${page.page}`} loading="lazy" />
        <figcaption>Page {page.page} · {page.width} × {page.height}</figcaption>
      </figure>)}</div>
      <button type="button" className="secondary-button compact" disabled={disabled || busy} onClick={() => onRemove(item.id)}>Remove from next review</button>
    </article>)}
  </section>;
}
