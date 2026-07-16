import assert from "node:assert/strict";
import test from "node:test";

import { shouldRenderIncompleteDurableToolCalls } from "./toolCallVisibility.ts";

void test("keeps an incomplete durable tool call visible while following a running session", () => {
  assert.equal(
    shouldRenderIncompleteDurableToolCalls(
      { type: "LATEST_FOLLOWING" },
      "running",
    ),
    true,
  );
});

void test("hides incomplete durable tool calls after the session becomes idle", () => {
  assert.equal(
    shouldRenderIncompleteDurableToolCalls(
      { type: "LATEST_FOLLOWING" },
      "idle",
    ),
    false,
  );
});

void test("does not project live running state into detached history", () => {
  assert.equal(
    shouldRenderIncompleteDurableToolCalls(
      {
        type: "DETACHED_HISTORY_BROWSING",
        hasNewer: true,
        newestCursor: "cursor",
      },
      "running",
    ),
    false,
  );
});
