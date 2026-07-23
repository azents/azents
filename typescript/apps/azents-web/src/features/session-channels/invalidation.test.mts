import assert from "node:assert/strict";
import test from "node:test";
import { sessionChannelDisconnectInvalidationPlan } from "./invalidation.ts";

void test("binding disconnect invalidates session and agent connection projections", () => {
  assert.deepEqual(sessionChannelDisconnectInvalidationPlan(), [
    "sessionChannels",
    "connections",
  ]);
});
