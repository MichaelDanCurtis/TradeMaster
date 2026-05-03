import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { dismissNotification, selectSymbol, setWorkspace, toggleSettings } from "./workspace-state.ts";

describe("workspace state helpers", () => {
  it("keeps agents as a valid workspace home state", () => {
    const state = { activeWorkspace: "agents" as const, selectedSymbol: "NVDA", settingsOpen: false };

    assert.equal(state.activeWorkspace, "agents");
  });

  it("changes workspace without changing selected symbol", () => {
    const next = setWorkspace({ activeWorkspace: "dashboard", selectedSymbol: "NVDA", settingsOpen: false }, "agents");

    assert.deepEqual(next, { activeWorkspace: "agents", selectedSymbol: "NVDA", settingsOpen: false });
  });

  it("changes selected symbol without changing workspace", () => {
    const next = selectSymbol({ activeWorkspace: "research", selectedSymbol: "NVDA", settingsOpen: false }, "AAPL");

    assert.deepEqual(next, { activeWorkspace: "research", selectedSymbol: "AAPL", settingsOpen: false });
  });

  it("toggles settings without replacing active workspace", () => {
    const next = toggleSettings({ activeWorkspace: "transactions", selectedSymbol: "NVDA", settingsOpen: false });

    assert.deepEqual(next, { activeWorkspace: "transactions", selectedSymbol: "NVDA", settingsOpen: true });
  });

  it("dismisses a notification by id", () => {
    const notifications = [
      { id: "a", severity: "info" as const, title: "A", body: "A", linkedWorkspace: "dashboard" as const },
      { id: "b", severity: "warning" as const, title: "B", body: "B", linkedWorkspace: "agents" as const }
    ];

    assert.deepEqual(dismissNotification(notifications, "a").map((item) => item.id), ["b"]);
  });
});
