import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  dismissNotification,
  selectSymbol,
  setWorkspace,
  visibleNotifications
} from "./workspace-state.ts";

describe("workspace state helpers", () => {
  it("keeps research as a valid workspace home state", () => {
    const state = { activeWorkspace: "research" as const, selectedSymbol: "NVDA" };

    assert.equal(state.activeWorkspace, "research");
  });

  it("changes workspace without changing selected symbol", () => {
    const next = setWorkspace({ activeWorkspace: "portfolio", selectedSymbol: "NVDA" }, "quant");

    assert.deepEqual(next, { activeWorkspace: "quant", selectedSymbol: "NVDA" });
  });

  it("changes selected symbol without changing workspace", () => {
    const next = selectSymbol({ activeWorkspace: "research", selectedSymbol: "NVDA" }, "AAPL");

    assert.deepEqual(next, { activeWorkspace: "research", selectedSymbol: "AAPL" });
  });

  it("treats current portfolio as a valid workspace", () => {
    const next = setWorkspace({ activeWorkspace: "portfolio", selectedSymbol: "NVDA" }, "portfolio");

    assert.deepEqual(next, { activeWorkspace: "portfolio", selectedSymbol: "NVDA" });
  });

  it("treats settings as a full workspace", () => {
    const next = setWorkspace({ activeWorkspace: "quant", selectedSymbol: "NVDA" }, "settings");

    assert.deepEqual(next, { activeWorkspace: "settings", selectedSymbol: "NVDA" });
  });

  it("dismisses a notification by id", () => {
    const notifications = [
      { id: "a", severity: "info" as const, title: "A", body: "A", linkedWorkspace: "portfolio" as const },
      { id: "b", severity: "warning" as const, title: "B", body: "B", linkedWorkspace: "research" as const }
    ];

    assert.deepEqual(dismissNotification(notifications, "a").map((item) => item.id), ["b"]);
  });

  it("suppresses notification toasts while settings is open", () => {
    const notifications = [
      { id: "a", severity: "info" as const, title: "A", body: "A", linkedWorkspace: "portfolio" as const }
    ];

    assert.deepEqual(
      visibleNotifications(
        { activeWorkspace: "settings", selectedSymbol: "NVDA" },
        notifications
      ),
      []
    );
    assert.deepEqual(
      visibleNotifications(
        { activeWorkspace: "research", selectedSymbol: "NVDA" },
        notifications
      ),
      notifications
    );
  });
});
