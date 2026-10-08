import assert from "node:assert/strict";
import test from "node:test";
import { projectLegacyAgentToolkitState } from "./legacyAgentToolkitState.ts";
import type { LegacyAgentToolkitSnapshot } from "./types.ts";

const snapshot: LegacyAgentToolkitSnapshot = {
  agentToolkits: [
    {
      id: "attachment-1",
      agent_id: "agent-1",
      toolkit_id: "toolkit-1",
      toolkit_type: "github",
      created_at: "2026-10-09T00:00:00Z",
    },
  ],
  availableToolkits: [],
  selectOptions: [{ value: "available-1", label: "Available Toolkit" }],
};
for (const [loading, failed, expected] of [
  [false, false, "READY"],
  [true, false, "LOADING"],
  [false, true, "ERROR"],
  [true, true, "LOADING_ERROR"],
] as const) {
  void test(`retains cached rows/options in ${expected}`, () => {
    const state = projectLegacyAgentToolkitState(snapshot, loading, failed);
    assert.equal(state.type, expected);
    assert.equal(state.agentToolkits, snapshot.agentToolkits);
    assert.equal(state.availableToolkits, snapshot.availableToolkits);
    assert.equal(state.selectOptions, snapshot.selectOptions);
  });
}
