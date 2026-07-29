import assert from "node:assert/strict";
import test from "node:test";

import {
  autoArchiveWarningDays,
  isAutoArchiveDueSoon,
} from "./auto-archive-urgency.ts";

const nowMs = Date.parse("2026-07-29T12:00:00Z");

void test("uses half of the TTL with fractional days discarded", () => {
  assert.equal(autoArchiveWarningDays(7), 3);
});

void test("caps the warning threshold at five days", () => {
  assert.equal(autoArchiveWarningDays(30), 5);
});

void test("disables the warning when the floored threshold is zero", () => {
  assert.equal(autoArchiveWarningDays(1), 0);
  assert.equal(isAutoArchiveDueSoon("2026-07-29T12:00:00Z", 1, nowMs), false);
});

void test("includes the exact TTL-derived warning boundary", () => {
  assert.equal(isAutoArchiveDueSoon("2026-08-01T12:00:00Z", 7, nowMs), true);
});

void test("excludes deadlines beyond the TTL-derived warning window", () => {
  assert.equal(isAutoArchiveDueSoon("2026-08-01T12:00:01Z", 7, nowMs), false);
});

void test("keeps overdue active sessions marked until archive completes", () => {
  assert.equal(isAutoArchiveDueSoon("2026-07-28T12:00:00Z", 30, nowMs), true);
});

void test("excludes missing and invalid automatic archive deadlines", () => {
  assert.equal(isAutoArchiveDueSoon(null, 30, nowMs), false);
  assert.equal(isAutoArchiveDueSoon("not-a-timestamp", 30, nowMs), false);
});
