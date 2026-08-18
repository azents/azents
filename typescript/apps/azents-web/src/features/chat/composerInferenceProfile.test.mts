import assert from "node:assert/strict";
import test from "node:test";
import { normalizeStoredInferenceProfile } from "./composerInferenceProfile.ts";

await test("preserves future reasoning effort strings", () => {
  assert.deepEqual(
    normalizeStoredInferenceProfile({
      model_target_label: "Default",
      reasoning_effort: "future-ultra",
    }),
    {
      model_target_label: "Default",
      reasoning_effort: "future-ultra",
    },
  );
});

await test("preserves null reasoning effort", () => {
  assert.deepEqual(
    normalizeStoredInferenceProfile({
      model_target_label: "Fast",
      reasoning_effort: null,
    }),
    {
      model_target_label: "Fast",
      reasoning_effort: null,
    },
  );
});

await test("rejects malformed persisted inference profiles", () => {
  assert.equal(normalizeStoredInferenceProfile(null), null);
  assert.equal(normalizeStoredInferenceProfile([]), null);
  assert.equal(
    normalizeStoredInferenceProfile({
      model_target_label: "",
      reasoning_effort: "high",
    }),
    null,
  );
  assert.equal(
    normalizeStoredInferenceProfile({
      model_target_label: "Default",
    }),
    null,
  );
  assert.equal(
    normalizeStoredInferenceProfile({
      model_target_label: "Default",
      reasoning_effort: 3,
    }),
    null,
  );
});
