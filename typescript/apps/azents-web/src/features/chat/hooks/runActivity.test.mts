import assert from "node:assert/strict";
import test from "node:test";

import {
  canAdoptLiveRunUpdatedEvent,
  canApplyAuthoritativeRunSnapshot,
  canApplyRunActivityEvent,
  canApplyRunStartedEvent,
  canApplyRunTerminalEvent,
  reconcileAuthoritativeRunIdentity,
  rememberTerminatedRunId,
  shouldContinueStopReconciliation,
  upsertCanonicalHistoryEvent,
} from "./runActivity.ts";

void test("run_started establishes the first non-terminal run identity", () => {
  assert.equal(canApplyRunStartedEvent(null, [], "run-a"), true);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, [], "run-a"), true);
  assert.equal(canApplyRunActivityEvent(null, "run-a"), false);
});

void test("run_started never replaces a different active run", () => {
  assert.equal(canApplyRunStartedEvent("run-a", [], "run-a"), true);
  assert.equal(canApplyRunStartedEvent("run-b", [], "run-a"), false);
});

void test("a delayed run_started cannot revive a terminal run", () => {
  assert.equal(canApplyRunStartedEvent(null, ["run-a"], "run-a"), false);
  assert.equal(canApplyRunStartedEvent(null, ["run-a"], "run-b"), true);
});

void test("run activity rejects a delayed event for another run", () => {
  assert.equal(canApplyRunActivityEvent("run-b", "run-a"), false);
  assert.equal(canAdoptLiveRunUpdatedEvent("run-b", [], "run-a"), false);
});

void test("compaction activity requires the exact active run identity", () => {
  assert.equal(canApplyRunActivityEvent("run-b", "run-b"), true);
  assert.equal(canApplyRunActivityEvent("run-b", "run-a"), false);
  assert.equal(canApplyRunActivityEvent(null, "run-a"), false);
});

void test("out-of-order durable upserts preserve canonical timeline order", () => {
  const eventThree = { id: "event-c", model_order: 3, value: "three" };
  const eventOne = { id: "event-a", model_order: 1, value: "one" };
  const eventTwoB = { id: "event-b", model_order: 2, value: "two-b" };
  const eventTwoA = { id: "event-a2", model_order: 2, value: "two-a" };

  let events = upsertCanonicalHistoryEvent([], eventThree);
  events = upsertCanonicalHistoryEvent(events, eventTwoB);
  events = upsertCanonicalHistoryEvent(events, eventOne);
  events = upsertCanonicalHistoryEvent(events, eventTwoA);
  events = upsertCanonicalHistoryEvent(events, {
    ...eventTwoB,
    value: "two-b-updated",
  });

  assert.deepEqual(
    events.map((event) => [event.id, event.value]),
    [
      ["event-a", "one"],
      ["event-a2", "two-a"],
      ["event-b", "two-b-updated"],
      ["event-c", "three"],
    ],
  );
});

void test("a delayed phase or authoritative snapshot cannot revive its terminal run", () => {
  assert.equal(canApplyRunActivityEvent(null, "run-a"), false);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, ["run-a"], "run-a"), false);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, ["run-a"], "run-b"), true);
  assert.equal(
    canApplyAuthoritativeRunSnapshot(null, ["run-a"], "run-a"),
    false,
  );
  assert.equal(
    canApplyAuthoritativeRunSnapshot(null, ["run-a"], "run-b"),
    true,
  );
  assert.equal(canApplyAuthoritativeRunSnapshot("run-a", [], "run-b"), true);
});

void test("multiple terminal run IDs remain protected from delayed revival", () => {
  let tombstones: string[] = [];
  tombstones = rememberTerminatedRunId(tombstones, "run-a");
  tombstones = rememberTerminatedRunId(tombstones, "run-b");

  assert.equal(canApplyRunStartedEvent(null, tombstones, "run-a"), false);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, tombstones, "run-b"), false);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, tombstones, "run-c"), true);
});

void test("terminal run tombstones remain unique for the mounted session", () => {
  let tombstones: string[] = [];
  for (let index = 0; index < 100; index += 1) {
    tombstones = rememberTerminatedRunId(tombstones, `run-${index}`);
  }
  tombstones = rememberTerminatedRunId(tombstones, "run-0");

  assert.equal(tombstones.length, 100);
  assert.equal(tombstones.at(-1), "run-0");
  assert.equal(tombstones.includes("run-1"), true);
  assert.equal(canAdoptLiveRunUpdatedEvent(null, tombstones, "run-1"), false);
});

void test("authoritative running snapshot replaces a stale active identity", () => {
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-a", [], {
      type: "PRESENT",
      runId: "run-b",
      isRunning: true,
    }),
    {
      applySnapshot: true,
      activeRunId: "run-b",
      terminatedRunIds: ["run-a"],
    },
  );
});

void test("a tombstoned authoritative snapshot cannot replace the active run", () => {
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-b", ["run-a"], {
      type: "PRESENT",
      runId: "run-a",
      isRunning: true,
    }),
    {
      applySnapshot: false,
      activeRunId: "run-b",
      terminatedRunIds: ["run-a"],
    },
  );
});

void test("authoritative absence terminates the currently active run", () => {
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-a", [], { type: "ABSENT" }),
    {
      applySnapshot: true,
      activeRunId: null,
      terminatedRunIds: ["run-a"],
    },
  );
});

void test("authoritative terminal snapshots never become active", () => {
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-a", [], {
      type: "PRESENT",
      runId: "run-a",
      isRunning: false,
    }),
    {
      applySnapshot: true,
      activeRunId: null,
      terminatedRunIds: ["run-a"],
    },
  );
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-b", [], {
      type: "PRESENT",
      runId: "run-a",
      isRunning: false,
    }),
    {
      applySnapshot: false,
      activeRunId: "run-b",
      terminatedRunIds: ["run-a"],
    },
  );
});

void test("an invalid authoritative snapshot preserves live identity", () => {
  assert.deepEqual(
    reconcileAuthoritativeRunIdentity("run-b", ["run-a"], {
      type: "INVALID",
    }),
    {
      applySnapshot: false,
      activeRunId: "run-b",
      terminatedRunIds: ["run-a"],
    },
  );
});

void test("run terminal events require an exact active run ID", () => {
  assert.equal(canApplyRunTerminalEvent("run-a", "run-a"), true);
  assert.equal(canApplyRunTerminalEvent("run-b", "run-a"), false);
  assert.equal(canApplyRunTerminalEvent(null, "run-a"), false);
});

void test("stop reconciliation is bounded and scoped to the stopped run", () => {
  assert.equal(
    shouldContinueStopReconciliation(
      "run-a",
      { type: "APPLIED", activeRunId: "run-a" },
      1,
      1,
    ),
    true,
  );
  assert.equal(
    shouldContinueStopReconciliation(
      "run-a",
      { type: "APPLIED", activeRunId: "run-a" },
      0,
      1,
    ),
    false,
  );
  assert.equal(
    shouldContinueStopReconciliation(
      "run-a",
      { type: "APPLIED", activeRunId: "run-a" },
      1,
      0,
    ),
    false,
  );
});

void test("a terminal WebSocket event still requires one REST snapshot", () => {
  assert.equal(
    shouldContinueStopReconciliation("run-a", { type: "NOT_APPLIED" }, 5, 1),
    true,
  );
  assert.equal(
    shouldContinueStopReconciliation(
      "run-a",
      { type: "APPLIED", activeRunId: null },
      5,
      1,
    ),
    false,
  );
  assert.equal(
    shouldContinueStopReconciliation(
      "run-a",
      { type: "APPLIED", activeRunId: "run-b" },
      5,
      1,
    ),
    false,
  );
});
