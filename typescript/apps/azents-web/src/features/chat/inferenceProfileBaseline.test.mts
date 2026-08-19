import assert from "node:assert/strict";
import test from "node:test";
import { resolveAppliedInferenceProfile } from "./inferenceProfileBaseline.ts";

void test("preserves an applied Session profile when its label is absent from Agent options", () => {
  const appliedProfile = {
    model_target_label: "Retired",
    reasoning_effort: "high" as const,
  };

  assert.deepEqual(
    resolveAppliedInferenceProfile(appliedProfile, {
      model_target_label: "Default",
      reasoning_effort: null,
    }),
    appliedProfile,
  );
});

void test("uses the current Agent baseline only when the Session profile is null", () => {
  const fallbackProfile = {
    model_target_label: "Default",
    reasoning_effort: null,
  };

  assert.deepEqual(
    resolveAppliedInferenceProfile(null, fallbackProfile),
    fallbackProfile,
  );
});
