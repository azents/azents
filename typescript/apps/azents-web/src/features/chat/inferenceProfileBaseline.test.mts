import assert from "node:assert/strict";
import test from "node:test";
import { resolveAppliedInferenceProfile } from "./inferenceProfileBaseline.ts";

void test("preserves an applied Session profile when its label is absent from Agent options", () => {
  const appliedProfile = {
    model_target_label: "Retired",
    reasoning_effort: "high" as const,
    enabled_execution_options: [],
  };

  assert.deepEqual(
    resolveAppliedInferenceProfile(appliedProfile, {
      model_target_label: "Default",
      reasoning_effort: null,
      enabled_execution_options: [],
    }),
    appliedProfile,
  );
});

void test("uses the current Agent baseline only when the Session profile is null", () => {
  const fallbackProfile = {
    model_target_label: "Default",
    reasoning_effort: null,
    enabled_execution_options: [],
  };

  assert.deepEqual(
    resolveAppliedInferenceProfile(null, fallbackProfile),
    fallbackProfile,
  );
});
