import assert from "node:assert/strict";
import { test } from "node:test";
import {
  age,
  linkedSource,
  pct,
  price,
  rankingReady,
  sameCapture,
  type PulseAnalysis,
  type PulseBoard,
} from "./market-pulse.ts";

test("missing and nonfinite market values remain missing, never zero", () => {
  assert.equal(pct(null), "—");
  assert.equal(pct(NaN), "—");
  assert.equal(price(Infinity), "—");
  assert.equal(pct(-1.25), "-1.25%");
  assert.equal(pct(0), "+0.00%");
  assert.equal(age(null, Date.now()), "No timestamp");
  assert.equal(age("bad-date", Date.now()), "Invalid time");
  assert.equal(
    age(new Date(Date.now() + 60_000).toISOString(), Date.now()),
    "Invalid time",
  );
});

test("analysis requires a recent capture with dated non-stale rankings", () => {
  const now = Date.now();
  const board = {
    snapshot_id: "current",
    captured_at: new Date(now).toISOString(),
    gainers: [{ symbol: "AAA", as_of: new Date(now - 60_000).toISOString() }],
    losers: [],
  } as unknown as PulseBoard;
  assert.equal(rankingReady(board, now), true);
  assert.equal(rankingReady(board, now + 901_000), false);
  board.gainers[0].as_of = null;
  assert.equal(rankingReady(board, now), false);
  board.gainers[0].as_of = new Date(now - 5 * 86400_000).toISOString();
  assert.equal(rankingReady(board, now), false);
});

test("explanations for old captures cannot be attached to new prices", () => {
  const board = { snapshot_id: "new" } as PulseBoard;
  const analysis = { packet: { snapshot_id: "old" } } as PulseAnalysis;
  assert.equal(sameCapture(board, analysis), false);
  analysis.packet!.snapshot_id = "new";
  assert.equal(sameCapture(board, analysis), true);
  assert.equal(sameCapture(board, null), false);
});

test("evidence links reject unsafe protocols and embedded credentials", () => {
  const analysis = {
    packet: {
      sources: [{ source_id: "news", url: "https://example.com/story" }],
    },
  } as PulseAnalysis;
  assert.equal(
    linkedSource(analysis, "news")?.url,
    "https://example.com/story",
  );
  assert.equal(linkedSource(analysis, "invented"), undefined);
  for (const url of [
    "javascript:alert(1)",
    "https://user:secret@example.com/story",
    "bad url",
  ]) {
    analysis.packet!.sources[0].url = url;
    assert.equal(linkedSource(analysis, "news"), undefined);
  }
});
