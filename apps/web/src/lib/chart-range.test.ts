import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { getWheelAdjustedRange } from "./chart-range.ts";

describe("chart range wheel stepping", () => {
  it("zooms into shorter market ranges on wheel up", () => {
    assert.equal(getWheelAdjustedRange("1M", -100), "5D");
    assert.equal(getWheelAdjustedRange("5D", -100), "1D");
    assert.equal(getWheelAdjustedRange("1D", -100), "1D");
  });

  it("zooms out to longer market ranges on wheel down", () => {
    assert.equal(getWheelAdjustedRange("1M", 100), "YTD");
    assert.equal(getWheelAdjustedRange("YTD", 100), "1Y");
    assert.equal(getWheelAdjustedRange("10Y", 100), "10Y");
  });

  it("ignores neutral wheel events", () => {
    assert.equal(getWheelAdjustedRange("1M", 0), "1M");
  });
});
