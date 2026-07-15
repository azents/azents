import assert from "node:assert/strict";
import test from "node:test";

import {
  applyStoppedRunProjection,
  createOptimisticInterruptedEvent,
  eventInterruptsRun,
  interruptedEventExternalId,
  liveActivityResponsePending,
  restoreRunActivityProjection,
  type RunActivityProjection,
  shouldProjectLivePartialEvent,
} from "./chatStopProjection.ts";

const SESSION_ID = "session-1";
const RUN_ID = "run-1";
const CREATED_AT = "2026-07-14T00:00:00.000Z";

void test("optimistic stop uses the durable interruption identity", () => {
  const event = createOptimisticInterruptedEvent(
    SESSION_ID,
    RUN_ID,
    CREATED_AT,
  );

  assert.equal(event.external_id, interruptedEventExternalId(RUN_ID));
  assert.equal(event.kind, "interrupted");
  assert.deepEqual(event.payload, {
    run_id: RUN_ID,
    reason: "user_requested",
  });
  assert.equal(event.created_at, CREATED_AT);
});

void test("interruption matching is scoped to the stopped run", () => {
  const event = createOptimisticInterruptedEvent(
    SESSION_ID,
    RUN_ID,
    CREATED_AT,
  );

  assert.equal(eventInterruptsRun(event, RUN_ID), true);
  assert.equal(eventInterruptsRun(event, "run-2"), false);
});

void test("optimistic stop immediately projects an idle composer state", () => {
  const runningState: RunActivityProjection & { preserved: string } = {
    liveRun: { run_id: RUN_ID },
    liveRunPhase: "streaming_model",
    sessionRunState: "running",
    isResponsePending: true,
    isCompacting: true,
    preserved: "current",
  };

  assert.deepEqual(applyStoppedRunProjection(runningState), {
    liveRun: null,
    liveRunPhase: null,
    sessionRunState: "idle",
    isResponsePending: false,
    isCompacting: false,
    preserved: "current",
  });
});

void test("delayed live activity cannot reactivate a stopped projection", () => {
  assert.equal(liveActivityResponsePending(false, true, true), false);
  assert.equal(liveActivityResponsePending(false, true, false), true);
});

void test("delayed partial output cannot render after the stop marker", () => {
  const interruptedEvent = createOptimisticInterruptedEvent(
    SESSION_ID,
    RUN_ID,
    CREATED_AT,
  );
  const delayedAssistantEvent = {
    kind: "assistant_message",
    payload: { content: "late output" },
  };

  assert.equal(
    shouldProjectLivePartialEvent(delayedAssistantEvent, RUN_ID),
    false,
  );
  assert.equal(shouldProjectLivePartialEvent(interruptedEvent, RUN_ID), true);
  assert.equal(
    shouldProjectLivePartialEvent(delayedAssistantEvent, null),
    true,
  );
});

void test("failed stop restores run activity without discarding newer state", () => {
  const previousState: RunActivityProjection & { preserved: string } = {
    liveRun: { run_id: RUN_ID },
    liveRunPhase: "streaming_model",
    sessionRunState: "running",
    isResponsePending: true,
    isCompacting: false,
    preserved: "before",
  };
  const currentState = {
    ...applyStoppedRunProjection(previousState),
    preserved: "after",
  };

  assert.deepEqual(restoreRunActivityProjection(currentState, previousState), {
    ...previousState,
    preserved: "after",
  });
});
