import assert from "node:assert/strict";
import test from "node:test";

import {
  formatElapsedDuration,
  startElapsedDurationTimer,
  visibleElapsedDurationSeconds,
} from "./elapsedDuration.ts";

const STARTED_AT = "2026-07-14T00:00:00.000Z";
const STARTED_AT_MS = Date.parse(STARTED_AT);

void test("elapsed duration stays hidden before its visibility threshold", () => {
  assert.equal(
    visibleElapsedDurationSeconds(STARTED_AT, STARTED_AT_MS + 9_999, 10),
    null,
  );
  assert.equal(
    visibleElapsedDurationSeconds(STARTED_AT, STARTED_AT_MS + 29_999, 30),
    null,
  );
});

void test("elapsed duration becomes visible at its threshold and increments", () => {
  assert.equal(
    visibleElapsedDurationSeconds(STARTED_AT, STARTED_AT_MS + 10_000, 10),
    10,
  );
  assert.equal(
    visibleElapsedDurationSeconds(STARTED_AT, STARTED_AT_MS + 31_000, 30),
    31,
  );
});

void test("elapsed duration formats seconds, minutes, and hours", () => {
  assert.equal(formatElapsedDuration(12), "12s");
  assert.equal(formatElapsedDuration(62), "1m 2s");
  assert.equal(formatElapsedDuration(3_723), "1h 2m 3s");
});

void test("elapsed duration timer cleanup clears the scheduled interval", () => {
  let scheduledDelay: number | null = null;
  let clearedTimerId: number | null = null;
  const cleanup = startElapsedDurationTimer(
    STARTED_AT,
    () => {},
    (_callback, delay) => {
      scheduledDelay = delay;
      return 42;
    },
    (timerId) => {
      clearedTimerId = timerId;
    },
  );

  assert.equal(scheduledDelay, 1_000);
  cleanup();
  assert.equal(clearedTimerId, 42);
});
