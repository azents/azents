import assert from "node:assert/strict";
import test from "node:test";

import {
  liveRetryDisplayKey,
  liveRunForDisplay,
  resolveDismissedLiveRetryKey,
} from "./liveRetryVisibility.ts";
import type { ChatLiveRunState } from "../types.ts";

function createLiveRun(
  runId: string,
  failedAttemptCount: number,
): ChatLiveRunState {
  return {
    run_id: runId,
    phase: "executing_tools",
    status: "running",
    inferenceProfile: {
      model_target_label: "planning",
      model_display_name: "Planning model",
      reasoning_effort: "high",
    },
    modelCallStartedAt: null,
    retry: {
      errorKind: "model_provider",
      status: "retrying",
      lastErrorMessage: "Provider request failed",
      failedAttemptCount,
      maxRetries: 3,
      backoffSeconds: 1,
      nextRetryAt: "2026-07-18T00:00:01Z",
      attempts: [],
    },
    operation: null,
  };
}

void test("hides only the retry UI after progress for the current attempt", () => {
  const liveRun = createLiveRun("run-1", 1);
  const displayed = liveRunForDisplay(liveRun, liveRetryDisplayKey(liveRun));

  assert.equal(displayed?.retry, null);
  assert.notEqual(liveRun.retry, null);
});

void test("keeps retry UI visible before streaming progress arrives", () => {
  const liveRun = createLiveRun("run-1", 1);

  assert.equal(liveRunForDisplay(liveRun, null), liveRun);
});

void test("shows retry UI again when another attempt fails", () => {
  const previousAttempt = createLiveRun("run-1", 1);
  const nextAttempt = createLiveRun("run-1", 2);

  assert.equal(
    liveRunForDisplay(nextAttempt, liveRetryDisplayKey(previousAttempt)),
    nextAttempt,
  );
});

void test("does not carry retry dismissal into another run", () => {
  const previousRun = createLiveRun("run-1", 1);
  const nextRun = createLiveRun("run-2", 1);

  assert.equal(
    liveRunForDisplay(nextRun, liveRetryDisplayKey(previousRun)),
    nextRun,
  );
});

void test("records retry dismissal when streaming progress is observed", () => {
  const liveRun = createLiveRun("run-1", 1);

  assert.equal(
    resolveDismissedLiveRetryKey(liveRun, null, true),
    liveRetryDisplayKey(liveRun),
  );
});

void test("restores retry dismissal from a retry-plus-partial snapshot", () => {
  const liveRun = createLiveRun("run-1", 1);

  const dismissedRetryKey = resolveDismissedLiveRetryKey(liveRun, null, true);

  assert.equal(liveRunForDisplay(liveRun, dismissedRetryKey)?.retry, null);
});

void test("clears retry dismissal when the failed attempt count changes", () => {
  const previousAttempt = createLiveRun("run-1", 1);
  const nextAttempt = createLiveRun("run-1", 2);

  assert.equal(
    resolveDismissedLiveRetryKey(
      nextAttempt,
      liveRetryDisplayKey(previousAttempt),
      false,
    ),
    null,
  );
});
