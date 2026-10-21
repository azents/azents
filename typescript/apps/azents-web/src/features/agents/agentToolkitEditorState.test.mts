import assert from "node:assert/strict";
import test from "node:test";
import {
  completedToolkitEditor,
  removedToolkitEditor,
} from "./agentToolkitManagementState.ts";
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

void test("successful detach and delete close the removed toolkit editor", () => {
  for (const type of ["DETAIL", "EDIT"] as const) {
    const submitted: AgentToolkitEditorState = {
      type,
      toolkitConfigId: "removed-toolkit",
    };
    assert.deepEqual(removedToolkitEditor(submitted, submitted), {
      type: "CLOSED",
    });
    const later: AgentToolkitEditorState = {
      type: "DETAIL",
      toolkitConfigId: "another-toolkit",
    };
    assert.equal(removedToolkitEditor(later, submitted), later);
  }
});
