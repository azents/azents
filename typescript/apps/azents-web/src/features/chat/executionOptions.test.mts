import assert from "node:assert/strict";
import test from "node:test";
import {
  executionOptionGroups,
  executionOptionIdsFromValue,
  normalizeComposerProfile,
  processingSpeedIntent,
  selectExecutionOptionInGroup,
} from "./executionOptions.ts";
import type {
  ModelExecutionOptionDefinition,
  RequestedInferenceProfile,
} from "@azents/public-client";

const definitions: ModelExecutionOptionDefinition[] = [
  {
    id: "fast",
    label: "Fast",
    description: "Requests faster processing; speed is not guaranteed.",
    cost_hint: "Additional API costs may apply.",
    control: "boolean",
    exclusive_group: "processing_speed",
  },
  {
    id: "ultrafast",
    label: "Ultrafast",
    description: "Requests faster processing; speed is not guaranteed.",
    cost_hint: "Additional API costs may apply.",
    control: "boolean",
    exclusive_group: "processing_speed",
  },
];
const profile: RequestedInferenceProfile = {
  model_target_label: "Default",
  reasoning_effort: "high",
  enabled_execution_options: ["fast"],
};

void test("supported members enumerate together without treating support as enabled", () => {
  assert.deepEqual(executionOptionGroups(definitions), [
    { id: "processing_speed", definitions },
  ]);
  assert.deepEqual(executionOptionGroups([]), []);
});

void test("premium switching replaces the group member and Normal clears it", () => {
  const ultrafast = selectExecutionOptionInGroup(
    profile,
    definitions,
    "processing_speed",
    "ultrafast",
  );
  assert.deepEqual(ultrafast, {
    ...profile,
    enabled_execution_options: ["ultrafast"],
  });
  assert.deepEqual(
    selectExecutionOptionInGroup(
      ultrafast,
      definitions,
      "processing_speed",
      "fast",
    ),
    profile,
  );
  assert.deepEqual(
    selectExecutionOptionInGroup(
      ultrafast,
      definitions,
      "processing_speed",
      "",
    ),
    { ...profile, enabled_execution_options: [] },
  );
  assert.deepEqual(profile.enabled_execution_options, ["fast"]);
});

void test("group relationships come from metadata and preserve unrelated groups and fields", () => {
  const unrelatedDefinitions = definitions.map((definition) => ({
    ...definition,
    exclusive_group:
      definition.id === "fast" ? "other_group" : "processing_speed",
  }));
  const next = selectExecutionOptionInGroup(
    profile,
    unrelatedDefinitions,
    "processing_speed",
    "ultrafast",
  );
  assert.deepEqual(next.enabled_execution_options, ["fast", "ultrafast"]);
  assert.equal(next.model_target_label, profile.model_target_label);
  assert.equal(next.reasoning_effort, profile.reasoning_effort);
  assert.deepEqual(
    selectExecutionOptionInGroup(
      next,
      unrelatedDefinitions,
      "processing_speed",
      "",
    ),
    profile,
  );
  assert.deepEqual(
    executionOptionGroups(
      definitions.map((definition) => ({
        ...definition,
        exclusive_group: null,
      })),
    ),
    [],
  );
});

void test("a missing group or unsupported selection cannot invent enabled intent", () => {
  const onlyUltrafast = definitions.filter(
    (definition) => definition.id === "ultrafast",
  );
  const normal: RequestedInferenceProfile = {
    ...profile,
    enabled_execution_options: [],
  };
  assert.equal(
    selectExecutionOptionInGroup(
      normal,
      onlyUltrafast,
      "processing_speed",
      "fast",
    ),
    normal,
  );
  assert.equal(
    selectExecutionOptionInGroup(normal, definitions, "missing", "ultrafast"),
    normal,
  );
  assert.deepEqual(
    selectExecutionOptionInGroup(
      normal,
      onlyUltrafast,
      "processing_speed",
      "ultrafast",
    ).enabled_execution_options,
    ["ultrafast"],
  );
});

void test("model switches intersect support without choosing a replacement premium member", () => {
  const ultrafast: RequestedInferenceProfile = {
    ...profile,
    enabled_execution_options: ["ultrafast"],
  };
  assert.deepEqual(
    normalizeComposerProfile(ultrafast, ["fast", "ultrafast"]),
    ultrafast,
  );
  assert.deepEqual(normalizeComposerProfile(ultrafast, ["fast"]), {
    ...ultrafast,
    enabled_execution_options: [],
  });
  assert.deepEqual(normalizeComposerProfile(ultrafast, []), {
    ...ultrafast,
    enabled_execution_options: [],
  });
});

void test("live IDs round-trip both premium options and retain invalid provenance as unknown", () => {
  assert.deepEqual(executionOptionIdsFromValue(["ultrafast"]), ["ultrafast"]);
  assert.deepEqual(executionOptionIdsFromValue(["fast"]), ["fast"]);
  assert.deepEqual(executionOptionIdsFromValue([]), []);
  for (const malformed of [
    null,
    void 0,
    "ultrafast",
    [1],
    ["future"],
    ["ultrafast", "ultrafast"],
  ]) {
    assert.equal(executionOptionIdsFromValue(malformed), null);
  }
});

void test("usage describes selected intent, including Normal, while unknown remains unknown", () => {
  assert.equal(processingSpeedIntent(null), null);
  assert.equal(processingSpeedIntent(profile), "fast");
  assert.equal(
    processingSpeedIntent({ enabled_execution_options: ["ultrafast"] }),
    "ultrafast",
  );
  assert.equal(
    processingSpeedIntent({ enabled_execution_options: [] }),
    "normal",
  );
  assert.equal(
    processingSpeedIntent({ enabled_execution_options: ["fast", "ultrafast"] }),
    null,
  );
});
