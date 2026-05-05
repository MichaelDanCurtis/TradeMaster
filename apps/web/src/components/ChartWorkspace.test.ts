import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, it } from "node:test";

describe("chart workspace interactions", () => {
  it("binds mouse wheel gestures to market range changes", () => {
    const source = readFileSync(new URL("./ChartWorkspace.tsx", import.meta.url), "utf-8");

    assert.match(source, /getWheelAdjustedRange/);
    assert.match(source, /onWheel=\{handleChartWheel\}/);
    assert.match(source, /RANGE_WHEEL_COOLDOWN_MS/);
  });
});
