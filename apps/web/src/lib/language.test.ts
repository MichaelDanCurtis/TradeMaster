import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { englishOrNotice } from "./language.ts";

describe("language display guard", () => {
  it("keeps English research text unchanged", () => {
    assert.equal(
      englishOrNotice("Risk review required before any paper order."),
      "Risk review required before any paper order."
    );
  });

  it("replaces CJK report text with an English notice", () => {
    assert.equal(
      englishOrNotice("高度估值敏感性；芯片供应链扰动风险；政策监管升级"),
      "Report text was returned in a non-English language. Re-run the report with the English-only research setting to regenerate this section."
    );
  });
});
