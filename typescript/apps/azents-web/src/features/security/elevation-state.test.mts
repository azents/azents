import assert from "node:assert/strict";
import test from "node:test";
import { synchronizeElevationState } from "./elevation-state.ts";
import type { ElevationState } from "./types.ts";
import type { AuthMethod } from "@azents/public-client";

const passwordMethod: AuthMethod = {
  type: "password",
  enabled: true,
  configured: true,
  valid: true,
  can_login: true,
  can_elevate: true,
  can_remove: true,
  unavailable_reason: null,
};

void test("a new mounted-page challenge resets a completed verifying flow", () => {
  const completedFlow: ElevationState = { type: "PASSWORD_VERIFYING" };

  assert.deepEqual(
    synchronizeElevationState({
      state: completedFlow,
      methods: [passwordMethod],
      reset: true,
    }),
    {
      type: "CHOOSE_METHOD",
      methods: [passwordMethod],
    },
  );
});

void test("method refresh does not interrupt an active verification", () => {
  const activeFlow: ElevationState = { type: "PASSWORD_VERIFYING" };

  assert.strictEqual(
    synchronizeElevationState({
      state: activeFlow,
      methods: [passwordMethod],
      reset: false,
    }),
    activeFlow,
  );
});
