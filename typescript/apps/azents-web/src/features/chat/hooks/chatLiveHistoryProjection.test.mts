import assert from "node:assert/strict";
import test from "node:test";

import { isLivePartialHistoryEvent } from "./chatLiveHistoryProjection.ts";

void test("interruption divider has no live projection source", () => {
  assert.equal(isLivePartialHistoryEvent("interrupted", false), false);
  assert.equal(isLivePartialHistoryEvent("assistant_message", false), true);
  assert.equal(isLivePartialHistoryEvent("goal_continuation", true), false);
});
