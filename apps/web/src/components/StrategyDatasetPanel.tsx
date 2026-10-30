"use client";

import { useState } from "react";
import { researchRequest, type Snapshot } from "@/lib/research-api";

export function StrategyDatasetPanel({ onImported }: { onImported: (snapshot: Snapshot) => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  async function run(work: () => Promise<void>) {
    setBusy(true); setError(""); setNotice("");
    try { await work(); }
    catch (e) { setError(e instanceof Error ? e.message : "Dataset action failed"); }
    finally { setBusy(false); }
  }

  async function download(path: string, filename: string) {
    const data = await researchRequest(path);
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url; link.download = filename; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="strategy-card strategy-form" aria-label="Research datasets">
    <h3>Data with a known history</h3>
    <p>Import a JSON dataset with raw prices, trading sessions, stable instrument identifiers and source availability. Financial facts need their original documents and publication times.</p>
    {error ? <p className="strategy-error" role="alert">{error}</p> : null}
    {notice ? <p role="status">{notice}</p> : null}
    <div className="strategy-actions">
      <button type="button" className="secondary-button compact" disabled={busy} onClick={() => void run(async () => {
        const snapshot = await researchRequest<Snapshot>("/fixtures/trend", {});
        await onImported(snapshot); setNotice("Synthetic dataset selected. Use the synthetic universe in the rules form and example dates in the plan.");
      })}>Load synthetic trend dataset</button>
      <button type="button" className="secondary-button compact" disabled={busy} onClick={() => void run(async () => {
        const snapshot = await researchRequest<Snapshot>("/fixtures/guidance", {});
        await onImported(snapshot); setNotice("Labelled synthetic guidance selected. Use the labelled guidance example rules and the 2020 example holdout. Classifier responses are hand-authored test data.");
      })}>Load labelled guidance dataset</button>
      <button type="button" className="secondary-button compact" disabled={busy} onClick={() => void run(() => download("/fixtures/trend/dataset", "trademaster-dataset-example.json"))}>Download example JSON</button>
      <button type="button" className="secondary-button compact" disabled={busy} onClick={() => void run(() => download("/datasets/schema", "trademaster-dataset-schema.json"))}>Download import schema</button>
    </div>
    <label>Import dataset JSON (maximum 50 MB)<input type="file" accept=".json,application/json" disabled={busy} onChange={(e) => {
      const file = e.target.files?.[0]; e.target.value = "";
      if (!file) return;
      void run(async () => {
        if (file.size > 50_000_000) throw new Error("Choose a dataset smaller than 50 MB.");
        const snapshot = await researchRequest<Snapshot>("/datasets", JSON.parse(await file.text()));
        await onImported(snapshot); setNotice("Dataset verified, stored immutably and selected for evaluation.");
      });
    }} /></label>
    <p>The synthetic example checks the software. Its prices cannot establish an investment edge or qualify for paper review.</p>
  </section>;
}
