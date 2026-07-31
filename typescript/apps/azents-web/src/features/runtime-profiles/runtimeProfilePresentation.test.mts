import assert from "node:assert/strict";
import test from "node:test";
import { runtimeProfileAvailabilityReason } from "./runtimeProfilePresentation.ts";

void test("maps unavailable Runtime Profile causes to stable presentation groups", () => {
  assert.equal(
    runtimeProfileAvailabilityReason("workspace_profile_disabled"),
    "workspaceProfileDisabled",
  );
  assert.equal(
    runtimeProfileAvailabilityReason("provider_disconnected"),
    "providerUnavailable",
  );
  assert.equal(
    runtimeProfileAvailabilityReason("infrastructure_profile_disabled"),
    "infrastructureProfileUnavailable",
  );
  assert.equal(
    runtimeProfileAvailabilityReason("provider_capability_missing"),
    "profileIncompatible",
  );
  assert.equal(runtimeProfileAvailabilityReason("future_reason"), "unknown");
});
