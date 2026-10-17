import assert from "node:assert/strict";
import test from "node:test";
import {
  agentAccessRequests,
  changeConnectionAgent,
  connectionAccessRequest,
  connectionAllows,
} from "./access-draft.ts";
import { personalToolFixture } from "./personal-tools-fixtures.ts";
import type { ConnectionAccessDraft } from "./access-draft.ts";

void test("First restriction sends only the exact negative intent, not a browser snapshot", () => {
  const draft: ConnectionAccessDraft = {
    baseline: personalToolFixture(),
    mode: "all",
    changes: {},
  };
  const restricted = changeConnectionAgent(draft, "agent-a", false);
  assert.equal(connectionAllows(restricted, "agent-a"), false);
  assert.equal(connectionAllows(restricted, "agent-b"), true);
  assert.deepEqual(connectionAccessRequest(restricted), {
    expected_mode: "all",
    mode: "selected",
    allow_agent_ids: [],
    restrict_agent_ids: ["agent-a"],
  });
  assert.equal(draft.mode, "all");
});

void test("Selected deltas preserve inaccessible and search-hidden memberships", () => {
  const draft: ConnectionAccessDraft = {
    baseline: personalToolFixture({
      access_mode: "selected",
      selected_agent_ids: ["hidden", "agent-b"],
    }),
    mode: "selected",
    changes: {},
  };
  const changed = changeConnectionAgent(
    changeConnectionAgent(draft, "agent-a", true),
    "agent-b",
    false,
  );
  assert.deepEqual(connectionAccessRequest(changed), {
    expected_mode: "selected",
    mode: null,
    allow_agent_ids: ["agent-a"],
    restrict_agent_ids: ["agent-b"],
  });
  assert.equal(connectionAllows(changed, "hidden"), true);
});

void test("An explicit All clears deltas and resumes dynamic policy", () => {
  assert.deepEqual(
    connectionAccessRequest({
      baseline: personalToolFixture({
        access_mode: "selected",
        selected_agent_ids: ["hidden"],
      }),
      mode: "all",
      changes: { "agent-a": false },
    }),
    {
      expected_mode: "selected",
      mode: "all",
      allow_agent_ids: [],
      restrict_agent_ids: [],
    },
  );
});

void test("Agent reenabling is only an exact positive delta and never resets All", () => {
  assert.deepEqual(
    agentAccessRequests(
      [
        personalToolFixture({
          id: "selected",
          access_mode: "selected",
          selected_agent_ids: ["hidden"],
        }),
        personalToolFixture({ id: "all" }),
      ],
      "agent-a",
      { selected: true, all: false },
    ),
    [
      {
        toolkit_id: "selected",
        expected_mode: "selected",
        mode: null,
        allow_agent_ids: ["agent-a"],
        restrict_agent_ids: [],
      },
      {
        toolkit_id: "all",
        expected_mode: "all",
        mode: null,
        allow_agent_ids: [],
        restrict_agent_ids: ["agent-a"],
      },
    ],
  );
});

void test("Toggling back to the baseline produces no Agent mutation", () => {
  assert.deepEqual(
    agentAccessRequests([personalToolFixture()], "agent-a", {
      "personal-example": true,
    }),
    [],
  );
});
