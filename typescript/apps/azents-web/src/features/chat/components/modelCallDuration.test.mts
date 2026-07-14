import assert from "node:assert/strict";
import test from "node:test";

import {
  startModelCallDurationTimer,
  visibleModelCallDurationSeconds,
} from "./modelCallDuration.ts";

const STARTED_AT = "2026-07-14T00:00:00.000Z";
const STARTED_AT_MS = Date.parse(STARTED_AT);

void test("model call duration stays hidden before ten seconds", () => {
  assert.equal(
    visibleModelCallDurationSeconds(STARTED_AT, STARTED_AT_MS + 9_999),
    null,
  );
});

void test("model call duration becomes visible at ten seconds and increments", () => {
  assert.equal(
    visibleModelCallDurationSeconds(STARTED_AT, STARTED_AT_MS + 10_000),
    10,
  );
  assert.equal(
    visibleModelCallDurationSeconds(STARTED_AT, STARTED_AT_MS + 11_000),
    11,
  );
});

void test("model call duration uses the replacement timestamp", () => {
  const nowMs = STARTED_AT_MS + 20_000;
  assert.equal(visibleModelCallDurationSeconds(STARTED_AT, nowMs), 20);
  assert.equal(
    visibleModelCallDurationSeconds(
      new Date(STARTED_AT_MS + 15_000).toISOString(),
      nowMs,
    ),
    null,
  );
});

void test("model call duration timer cleanup clears the scheduled interval", () => {
  let scheduledDelay: number | null = null;
  let clearedTimerId: number | null = null;
  let tickCount = 0;
  const cleanup = startModelCallDurationTimer(
    STARTED_AT,
    () => {
      tickCount += 1;
    },
    (_callback, delay) => {
      scheduledDelay = delay;
      return 42;
    },
    (timerId) => {
      clearedTimerId = timerId;
    },
  );

  assert.equal(scheduledDelay, 1000);
  assert.equal(tickCount, 0);
  cleanup();
  assert.equal(clearedTimerId, 42);
});
