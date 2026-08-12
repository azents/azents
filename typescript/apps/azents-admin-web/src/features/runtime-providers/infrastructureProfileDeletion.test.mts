import assert from "node:assert/strict";
import test from "node:test";
import {
  infrastructureProfileDeletionConfirmationEnabled,
  infrastructureProfileDeletionFailureMessage,
  nextDeletionReferenceOffset,
  previousDeletionReferenceOffset,
} from "./infrastructureProfileDeletion.ts";

void test("maps bounded deletion conflicts to actionable Admin copy", () => {
  assert.equal(
    infrastructureProfileDeletionFailureMessage(
      JSON.stringify({ code: "profile_version_conflict", current_version: 4 }),
    ),
    "The Profile changed. Review the refreshed impact before deleting.",
  );
  assert.equal(
    infrastructureProfileDeletionFailureMessage(
      JSON.stringify({
        code: "profile_referenced",
        blocking_reference_count: 2,
      }),
    ),
    "A current Workspace Runtime Profile now references this Profile.",
  );
  assert.equal(
    infrastructureProfileDeletionFailureMessage(
      JSON.stringify({ code: "profile_not_found" }),
    ),
    "The Profile was already deleted or is no longer available.",
  );
});

void test("preserves unknown or non-structured deletion failures", () => {
  assert.equal(
    infrastructureProfileDeletionFailureMessage("Network request failed"),
    "Network request failed",
  );
  assert.equal(
    infrastructureProfileDeletionFailureMessage(
      JSON.stringify({ code: "future_conflict" }),
    ),
    JSON.stringify({ code: "future_conflict" }),
  );
});

void test("bounds deletion reference pagination", () => {
  assert.equal(previousDeletionReferenceOffset(0, 50), 0);
  assert.equal(previousDeletionReferenceOffset(50, 50), 0);
  assert.equal(previousDeletionReferenceOffset(100, 50), 50);
  assert.equal(nextDeletionReferenceOffset(0, 50, 50, 101), 50);
  assert.equal(nextDeletionReferenceOffset(100, 50, 1, 101), 100);
});

void test("cached impact cannot authorize deletion while a fresh lookup is pending", () => {
  assert.equal(
    infrastructureProfileDeletionConfirmationEnabled({
      refreshPending: true,
      impactError: false,
      blockingReferenceCount: 0,
    }),
    false,
  );
  assert.equal(
    infrastructureProfileDeletionConfirmationEnabled({
      refreshPending: false,
      impactError: false,
      blockingReferenceCount: 0,
    }),
    true,
  );
  assert.equal(
    infrastructureProfileDeletionConfirmationEnabled({
      refreshPending: false,
      impactError: false,
      blockingReferenceCount: 1,
    }),
    false,
  );
});
