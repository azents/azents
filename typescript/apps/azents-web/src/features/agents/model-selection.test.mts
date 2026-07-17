import assert from "node:assert/strict";
import test from "node:test";

import {
  createSelectableModelOptionFormValue,
  fallbackSelectableModelLabel,
  isSubagentGuidanceWithinLimit,
  type SelectableModelOptionFormValue,
  selectableModelOptionInputsFromFormValues,
} from "./model-selection.ts";

function option(id: string, label: string): SelectableModelOptionFormValue {
  return {
    id,
    label,
    model_provider_integration_id: null,
    model_selection_value: null,
    model_display_name: null,
    model_identifier: null,
    normalized_capabilities: null,
    context_window_tokens: null,
    max_output_tokens: null,
    builtin_tools: [],
    subagent_enabled: true,
    subagent_guidance: null,
  };
}

void test("a pending first row preserves a valid selected model label", () => {
  const options = [
    option("pending", ""),
    option("default", "default"),
    option("lightweight", "lightweight"),
  ];

  assert.equal(fallbackSelectableModelLabel("default", options), "default");

  options[0] = option("pending", "new-model");
  assert.equal(fallbackSelectableModelLabel("default", options), "default");
});

void test("an invalid label falls back to the first non-empty option", () => {
  const options = [
    option("pending", ""),
    option("default", "default"),
    option("lightweight", "lightweight"),
  ];

  assert.equal(fallbackSelectableModelLabel("removed", options), "default");
  assert.equal(fallbackSelectableModelLabel(null, options), "default");
});

void test("new selectable options enable explicit subagent selection", () => {
  const created = createSelectableModelOptionFormValue("new-option");

  assert.equal(created.subagent_enabled, true);
  assert.equal(created.subagent_guidance, null);
});

void test("selectable model input mapping preserves and normalizes subagent policy", () => {
  const configured = {
    ...option("lightweight", "lightweight"),
    model_selection_value: "integration-1:model-1",
    subagent_enabled: false,
    subagent_guidance: "  Prefer for bounded investigation.  ",
  };

  assert.deepEqual(selectableModelOptionInputsFromFormValues([configured]), [
    {
      label: "lightweight",
      model_selection: {
        llm_provider_integration_id: "integration-1",
        model_identifier: "model-1",
      },
      settings: {
        context_window_tokens: null,
        max_output_tokens: null,
        builtin_tools: [],
        subagent_enabled: false,
        subagent_guidance: "Prefer for bounded investigation.",
      },
    },
  ]);
});

void test("subagent guidance is bounded to 500 characters", () => {
  assert.equal(isSubagentGuidanceWithinLimit("x".repeat(500)), true);
  assert.equal(isSubagentGuidanceWithinLimit("x".repeat(501)), false);
  assert.equal(isSubagentGuidanceWithinLimit(null), true);
});
