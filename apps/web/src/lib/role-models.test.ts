import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { ALL_ROLES, COORDINATOR_ROLES, resolveRoleModel } from "./role-models.ts";

describe("resolveRoleModel", () => {
  it("returns fallback when roleModels is null or empty", () => {
    assert.equal(resolveRoleModel("market_analyst", null, "fb"), "fb");
    assert.equal(resolveRoleModel("market_analyst", {}, "fb"), "fb");
  });

  it("returns tier defaults for coordinator vs agent roles", () => {
    const cfg = { coordinator: "deep", agent: "quick" };
    assert.equal(resolveRoleModel("research_manager", cfg, "fb"), "deep");
    assert.equal(resolveRoleModel("portfolio_manager", cfg, "fb"), "deep");
    assert.equal(resolveRoleModel("trader", cfg, "fb"), "deep");
    assert.equal(resolveRoleModel("market_analyst", cfg, "fb"), "quick");
    assert.equal(resolveRoleModel("bull_researcher", cfg, "fb"), "quick");
  });

  it("per-role override beats tier default", () => {
    const cfg = {
      coordinator: "deep",
      agent: "quick",
      overrides: { portfolio_manager: "boss", bull_researcher: "stronger" }
    };
    assert.equal(resolveRoleModel("portfolio_manager", cfg, "fb"), "boss");
    assert.equal(resolveRoleModel("bull_researcher", cfg, "fb"), "stronger");
    // Unaffected roles fall through to tier
    assert.equal(resolveRoleModel("research_manager", cfg, "fb"), "deep");
    assert.equal(resolveRoleModel("market_analyst", cfg, "fb"), "quick");
  });

  it("empty-string tier default is ignored, falls through to fallback", () => {
    const cfg = { coordinator: "", agent: "quick" };
    assert.equal(resolveRoleModel("research_manager", cfg, "fb"), "fb");
    assert.equal(resolveRoleModel("market_analyst", cfg, "fb"), "quick");
  });

  it("coordinator membership matches the Python side exactly", () => {
    assert.deepEqual(
      Array.from(COORDINATOR_ROLES).sort(),
      ["portfolio_manager", "research_designer", "research_manager", "trader"]
    );
  });

  it("ALL_ROLES includes the designer and evidence extractor", () => {
    assert.equal(ALL_ROLES.length, 16);
    assert.equal(resolveRoleModel("research_designer", { coordinator: "deep" }, "fallback"), "deep");
    assert.equal(resolveRoleModel("research_extractor", { agent: "quick" }, "fallback"), "quick");
  });
});
