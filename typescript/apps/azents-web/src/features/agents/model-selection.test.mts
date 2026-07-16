import assert from "node:assert/strict";
import test from "node:test";

import {
  fallbackSelectableModelLabel,
  type SelectableModelOptionFormValue,
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
