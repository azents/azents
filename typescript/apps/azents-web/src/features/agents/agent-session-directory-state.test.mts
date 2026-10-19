import assert from "node:assert/strict";
import test from "node:test";
import { projectAgentSessionDirectoryQueryState } from "./agent-session-directory-state.ts";

void test("directory query phases preserve snapshot identity and existing error precedence", () => {
  const snapshot = {
    sessions: [],
    totalCount: 52,
    currentArchiveRetentionDays: null,
  };
  for (const pending of [true, false]) {
    for (const error of [null, "", "Query failed."]) {
      const state = projectAgentSessionDirectoryQueryState(
        snapshot,
        pending,
        error,
      );
      assert.equal(state.snapshot, snapshot);
      assert.equal(
        state.type,
        pending ? "LOADING" : error ? "ERROR" : "LOADED",
      );
      if (state.type !== "LOADED") {
        assert.equal(state.message, error);
      }
      const showError = state.type !== "LOADED" && Boolean(state.message);
      assert.equal(showError, Boolean(error));
      assert.equal(state.type === "LOADING", pending);
      assert.equal(state.type === "LOADED", !pending && !error);
    }
  }
});
