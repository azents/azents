import assert from "node:assert/strict";
import test from "node:test";
import { externalChannelSettingsInvalidationPlan } from "./invalidation.ts";

void test("connection lifecycle mutations invalidate connection projections", () => {
  for (const mutation of [
    "setup",
    "validate",
    "switchTransport",
    "reconnect",
  ] as const) {
    assert.deepEqual(externalChannelSettingsInvalidationPlan(mutation), [
      "connections",
    ]);
  }
});

void test("terminal connection disconnect also invalidates session channels", () => {
  assert.deepEqual(externalChannelSettingsInvalidationPlan("disconnect"), [
    "connections",
    "sessionChannels",
  ]);
});

void test("access mutations invalidate every projection that exposes them", () => {
  assert.deepEqual(externalChannelSettingsInvalidationPlan("revokeGrant"), [
    "agentAccess",
    "sessionChannels",
  ]);
  assert.deepEqual(externalChannelSettingsInvalidationPlan("removeBlock"), [
    "agentAccess",
  ]);
});
