import assert from "node:assert/strict";
import test from "node:test";

import {
  shouldPollAgentWorkspaceLifecycle,
  shouldPollRuntimeLifecycle,
} from "./runtimeLifecycle.ts";
import type { AgentRuntimeLifecyclePresentationResponse } from "@azents/public-client";

const stable: AgentRuntimeLifecyclePresentationResponse = {
  target: "running",
  convergence: "stable",
  provider: { connection: "connected", resource: "running" },
  runner: { state: "ready" },
  availability: "ready",
  reason_code: null,
  desired_generation: 3,
};

void test("polls only while server lifecycle authority is not stable", () => {
  assert.equal(shouldPollRuntimeLifecycle(stable), false);
  assert.equal(
    shouldPollRuntimeLifecycle({ ...stable, convergence: "starting" }),
    true,
  );
  assert.equal(shouldPollRuntimeLifecycle(stable, { removing: true }), true);
  assert.equal(
    shouldPollRuntimeLifecycle(stable, {
      configurationStatus: "waiting_for_recreation",
    }),
    true,
  );
});

void test("keeps Workspace access and recreation polling additive", () => {
  assert.equal(
    shouldPollAgentWorkspaceLifecycle({
      lifecycle: stable,
      workspace: { type: "CONNECTING" },
    }),
    true,
  );
  assert.equal(
    shouldPollAgentWorkspaceLifecycle({
      lifecycle: stable,
      workspace: {
        type: "CONTROL_UNAVAILABLE",
        detail: "Runner operation target is temporarily unavailable.",
        retry_after_ms: 1000,
      },
    }),
    true,
  );
  assert.equal(
    shouldPollAgentWorkspaceLifecycle(
      {
        lifecycle: stable,
        workspace: { type: "UNAVAILABLE", reason: "RUNTIME_NOT_RUNNING" },
      },
      { configurationStatus: "waiting_for_recreation" },
    ),
    true,
  );
  assert.equal(
    shouldPollAgentWorkspaceLifecycle({
      lifecycle: stable,
      workspace: { type: "UNAVAILABLE", reason: "RUNTIME_NOT_RUNNING" },
    }),
    false,
  );
});
