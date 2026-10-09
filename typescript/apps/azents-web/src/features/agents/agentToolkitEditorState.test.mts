import assert from "node:assert/strict";
import test from "node:test";
import { completedToolkitEditor } from "./agentToolkitManagementState.ts";
import type { AgentToolkitEditorState } from "./types";

void test("a completed write cannot close another editor, even for the same type", () => {
  const submitted: AgentToolkitEditorState = {
    type: "CREATE",
    toolkitType: "mcp",
  };
  const later: AgentToolkitEditorState = { type: "CREATE", toolkitType: "mcp" };
  assert.equal(completedToolkitEditor(later, submitted), later);
  assert.deepEqual(completedToolkitEditor(submitted, submitted), {
    type: "CLOSED",
  });
  const edit: AgentToolkitEditorState = {
    type: "EDIT",
    toolkitConfigId: "exact-toolkit",
  };
  assert.deepEqual(completedToolkitEditor(edit, edit), {
    type: "DETAIL",
    toolkitConfigId: "exact-toolkit",
  });
});
