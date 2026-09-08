import assert from "node:assert/strict";
import test from "node:test";
import { projectAgentToolkitManagementState } from "../agentToolkitManagementState.ts";

void test("projects loading and error states without toolkit data", () => {
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: true,
      error: null,
    }),
    { type: "LOADING" },
  );
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: false,
      error: "Agent administrator access required",
    }),
    { type: "ERROR", message: "Agent administrator access required" },
  );
});

void test("projects shared candidates into stable select options", () => {
  assert.deepEqual(
    projectAgentToolkitManagementState({
      loading: false,
      error: null,
      data: {
        items: [],
        available_shared: [
          { id: "toolkit-1", name: "Workspace GitHub", toolkit_type: "github" },
        ],
      },
      toolkitDefinitions: [
        { slug: "github", name: "GitHub" },
        { slug: "shell", name: "Shell" },
      ],
    }),
    {
      type: "READY",
      items: [],
      toolkitTypes: [{ value: "github", label: "GitHub" }],
      availableShared: [
        {
          value: "toolkit-1",
          label: "Workspace GitHub (github)",
          toolkitType: "github",
        },
      ],
    },
  );
});
