import assert from "node:assert/strict";
import test from "node:test";
import {
  accountLinkStatusColor,
  candidateNextAction,
  elevationScreenState,
  isRecoverableWithFreshCandidate,
  preserveLastSafeOrigin,
} from "./presentation.ts";

void test("candidate states require explicit status check and final confirmation", () => {
  assert.equal(candidateNextAction("pending_provider_proof"), "check_status");
  assert.equal(candidateNextAction("provider_verified"), "confirm");
  assert.equal(candidateNextAction("connected"), "connected");
});

void test("terminal candidate states require a fresh candidate", () => {
  assert.equal(candidateNextAction("cancelled"), "start_fresh");
  assert.equal(candidateNextAction("expired"), "start_fresh");
  assert.equal(isRecoverableWithFreshCandidate("expired"), true);
  assert.equal(isRecoverableWithFreshCandidate("candidate_terminal"), true);
  assert.equal(isRecoverableWithFreshCandidate("conflict"), false);
});

void test("link status presentation distinguishes inactive membership", () => {
  assert.equal(accountLinkStatusColor("active"), "green");
  assert.equal(accountLinkStatusColor("inactive"), "yellow");
  assert.equal(accountLinkStatusColor("revoked"), "gray");
});

void test("elevation waits for the real methods response", () => {
  assert.equal(
    elevationScreenState({ hasResponse: false, isError: false }),
    "loading",
  );
  assert.equal(
    elevationScreenState({ hasResponse: false, isError: true }),
    "error",
  );
  assert.equal(
    elevationScreenState({ hasResponse: true, isError: false }),
    "ready",
  );
});

void test("terminal refetch preserves the last authorized provider return context", () => {
  const safeOrigin = { id: "origin-1", returnUrl: "https://provider.example" };

  assert.strictEqual(preserveLastSafeOrigin(null, safeOrigin), safeOrigin);
  assert.strictEqual(preserveLastSafeOrigin(safeOrigin, null), safeOrigin);
});
