import assert from "node:assert/strict";
import test from "node:test";
import { runtimeProviderReadiness } from "./runtimeProviderPresentation.ts";

const activeProvider = {
  enabled: true,
  lifecycle_state: "active",
  current_contract_revision_id: "current-contract",
};

void test("current advertisement is authoritative without a review action", () => {
  assert.deepEqual(runtimeProviderReadiness(activeProvider), {
    color: "green",
    label: "Ready",
  });
});

void test("missing current advertisement is pending", () => {
  assert.deepEqual(
    runtimeProviderReadiness({
      ...activeProvider,
      current_contract_revision_id: null,
    }),
    { color: "yellow", label: "Contract pending" },
  );
});
