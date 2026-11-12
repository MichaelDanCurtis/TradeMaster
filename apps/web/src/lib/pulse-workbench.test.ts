import assert from "node:assert/strict";
import { test } from "node:test";
import { DEFAULT_DESK, readDesk } from "./pulse-workbench.ts";
test("desk preferences reject corrupt storage and clamp unusable widths", () => {
  assert.deepEqual(readDesk("{broken"), DEFAULT_DESK);
  assert.deepEqual(
    readDesk(JSON.stringify({ dock: "outside", width: 99999, tab: "orders" })),
    { dock: "bottom", width: 900, tab: "catalyst" },
  );
  assert.equal(readDesk(JSON.stringify({ width: -10 })).width, 320);
  assert.equal(readDesk(JSON.stringify({ width: "500" })).width, 800);
});
test("valid dock, size and selected tab survive reload", () => {
  const layout = { dock: "left", width: 540, tab: "charts" };
  assert.deepEqual(readDesk(JSON.stringify(layout)), layout);
  assert.equal(
    readDesk(JSON.stringify({ dock: "bottom", tab: "company" })).dock,
    "bottom",
  );
});
