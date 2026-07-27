import assert from "node:assert/strict";
import test from "node:test";
import { runtimeProviderReadiness } from "./runtimeProviderPresentation.ts";

const activeProvider = {
  enabled: true,
  lifecycle_state: "active",
  accepted_contract_revision_id: "accepted-contract",
  current_contract_revision_id: "accepted-contract",
};

void test("accepted current advertisement is ready without a review action", () => {
  assert.deepEqual(runtimeProviderReadiness(activeProvider), {
    color: "green",
    label: "Ready",
  });
});

void test("drifted current advertisement requires review", () => {
  assert.deepEqual(
    runtimeProviderReadiness({
      ...activeProvider,
      current_contract_revision_id: "candidate-contract",
    }),
    { color: "yellow", label: "Review required" },
  );
});

void test("missing current advertisement is pending even with accepted history", () => {
  assert.deepEqual(
    runtimeProviderReadiness({
      ...activeProvider,
      current_contract_revision_id: null,
    }),
    { color: "yellow", label: "Contract pending" },
  );
});
