import assert from "node:assert/strict";
import test from "node:test";
import { recentBrowserTargets } from "./recentTargets.ts";

const page = { task_id: "task", id: "page", resource_incarnation: "current" };
const event = {
  id: "2",
  created_at: "2026-10-15T10:00:00Z",
  kind: "client_tool_result",
  payload: {
    call_id: "call",
    name: "browser_act",
    status: "completed",
    output: JSON.stringify({ page }),
  },
} as const;

void test("recent browser targets use completed tool results in newest-first order", () => {
  const older = {
    ...event,
    id: "1",
    created_at: "2026-10-15T09:00:00Z",
    payload: {
      ...event.payload,
      output: JSON.stringify({ page: { ...page, id: "older" } }),
    },
  };
  assert.deepEqual(recentBrowserTargets([older, event, event]), [
    { task_id: "task", page_id: "page", resource_incarnation: "current" },
    { task_id: "task", page_id: "older", resource_incarnation: "current" },
  ]);
});
void test("tool names can come from the paired call and outputs can be text parts", () => {
  assert.equal(
    recentBrowserTargets([
      {
        ...event,
        id: "1",
        kind: "client_tool_call",
        payload: { call_id: "call", name: "browser_open" },
      },
      {
        ...event,
        payload: {
          call_id: "call",
          status: "completed",
          output: [{ type: "text", text: JSON.stringify({ page }) }],
        },
      },
    ])[0]?.page_id,
    "page",
  );
});
void test("failed, malformed, unrelated or pageless results never supply preference", () => {
  for (const payload of [
    { ...event.payload, status: "failed" },
    { ...event.payload, name: "exec_command" },
    { ...event.payload, output: "not json" },
    { ...event.payload, output: JSON.stringify({ page: null }) },
    {
      ...event.payload,
      output: JSON.stringify({ page: { ...page, task_id: true } }),
    },
  ]) {
    assert.deepEqual(recentBrowserTargets([{ ...event, payload }]), []);
  }
});
