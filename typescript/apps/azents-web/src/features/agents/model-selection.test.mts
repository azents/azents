import assert from "node:assert/strict";
import test from "node:test";

import {
  copyCompatiblePrimarySettings,
  createSelectableModelCandidateFormValue,
  createSelectableModelOptionFormValue,
  fallbackSelectableModelLabel,
  hasDuplicateSelectableModelCandidates,
  hasInvalidImageGenerationSelections,
  imageGenerationModelIdentifier,
  imageGenerationModelSelectionVisible,
  isSubagentGuidanceWithinLimit,
  modelContextBadgeValue,
  resolveModelContextRange,
  type SelectableModelCandidateFormValue,
  type SelectableModelOptionFormValue,
  selectableModelOptionInputsFromFormValues,
  selectCandidateIntegration,
  selectCandidateModel,
  withImageGenerationModelIdentifier,
} from "./model-selection.ts";
import type { ModelCapabilities } from "@azents/public-client";

function candidate(id: string): SelectableModelCandidateFormValue {
  return createSelectableModelCandidateFormValue(id);
}

function option(id: string, label: string): SelectableModelOptionFormValue {
  return {
    id,
    label,
    candidates: [candidate(`${id}-candidate`)],
    subagent_enabled: true,
    subagent_guidance: null,
  };
}

function capabilities(
  tools: string[],
  maxInputTokens = 64_000,
  maxOutputTokens = 32_000,
): ModelCapabilities {
  return {
    reasoning: { supported: false, effort_levels: [] },
    built_in_tools: { supported: tools },
    context_window: {
      max_input_tokens: maxInputTokens,
      max_output_tokens: maxOutputTokens,
    },
    modalities: { input: ["text"], output: ["text"] },
    tool_calling: { supported: true },
    parameters: {},
    compatibility: {},
  };
}

void test("model replacement preserves every shared capability preference", () => {
  const configured = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-1",
    model_selection_value: "integration-1:model-a",
    normalized_capabilities: capabilities([
      "web_search",
      "image_generation",
      "code_execution",
      "retired_tool",
    ]),
    context_window_tokens: 32_000,
    max_output_tokens: 8_000,
    builtin_tools: ["code_execution", "retired_tool"],
    builtin_tool_configs: {
      code_execution: { limit: 3 },
      retired_tool: { limit: 1 },
    },
  };

  const replacement = selectCandidateModel(configured, {
    provider: "provider",
    model_identifier: "model-b",
    model_display_name: "Model B",
    normalized_capabilities: capabilities([
      "image_generation",
      "web_search",
      "code_execution",
      "new_tool",
    ]),
  });

  assert.equal(replacement.model_selection_value, "integration-1:model-b");
  assert.equal(replacement.context_window_tokens, 32_000);
  assert.equal(replacement.max_output_tokens, 8_000);
  assert.deepEqual(replacement.builtin_tools, ["code_execution", "new_tool"]);
  assert.deepEqual(replacement.builtin_tool_configs, {
    code_execution: { limit: 3 },
    new_tool: {},
  });
});

void test("switching integrations retains preferences but drops provider-specific config", () => {
  const configured = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-a",
    model_selection_value: "integration-a:model-a",
    normalized_capabilities: capabilities(["web_search", "image_generation"]),
    context_window_tokens: 48_000,
    max_output_tokens: 16_000,
    builtin_tools: ["image_generation"],
    builtin_tool_configs: {
      image_generation: { model: "image-model-a" },
    },
  };

  const pending = selectCandidateIntegration(configured, "integration-b");
  assert.equal(pending.model_selection_value, null);
  assert.equal(pending.model_provider_integration_id, "integration-b");
  assert.deepEqual(pending.builtin_tools, ["image_generation"]);
  assert.deepEqual(pending.builtin_tool_configs, {});

  const replacement = selectCandidateModel(pending, {
    provider: "provider-b",
    model_identifier: "model-b",
    model_display_name: "Model B",
    normalized_capabilities: capabilities(
      ["image_generation", "web_search"],
      32_000,
      8_000,
    ),
  });
  assert.equal(replacement.model_selection_value, "integration-b:model-b");
  assert.equal(replacement.context_window_tokens, null);
  assert.equal(replacement.max_output_tokens, null);
  assert.deepEqual(replacement.builtin_tools, ["image_generation"]);
  assert.deepEqual(replacement.builtin_tool_configs, { image_generation: {} });
});

void test("replacement within one integration keeps image generation configuration", () => {
  const configured = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-a",
    normalized_capabilities: capabilities(["image_generation", "web_search"]),
    builtin_tools: ["image_generation"],
    builtin_tool_configs: {
      image_generation: { model: "pinned-image-model", quality: "high" },
    },
  };
  const pending = selectCandidateIntegration(configured, "integration-a");
  const replacement = selectCandidateModel(pending, {
    provider: "provider",
    model_identifier: "model-b",
    model_display_name: "Model B",
    normalized_capabilities: capabilities(["image_generation", "web_search"]),
  });

  assert.deepEqual(replacement.builtin_tools, ["image_generation"]);
  assert.deepEqual(replacement.builtin_tool_configs, {
    image_generation: { model: "pinned-image-model", quality: "high" },
  });
});

void test("initial model selection enables supported tools by default", () => {
  const pending = selectCandidateIntegration(candidate("new"), "integration-a");
  const selected = selectCandidateModel(pending, {
    provider: "provider",
    model_identifier: "model-a",
    model_display_name: "Model A",
    normalized_capabilities: capabilities(["web_search", "image_generation"]),
  });
  assert.deepEqual(selected.builtin_tools, ["web_search", "image_generation"]);
  assert.deepEqual(selected.builtin_tool_configs, {
    web_search: {},
    image_generation: {},
  });
});

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
    candidates: [
      {
        ...candidate("lightweight-candidate"),
        model_selection_value: "integration-1:model-1",
      },
    ],
    subagent_enabled: false,
    subagent_guidance: "  Prefer for bounded investigation.  ",
  };

  assert.deepEqual(selectableModelOptionInputsFromFormValues([configured]), [
    {
      label: "lightweight",
      candidates: [
        {
          model_selection: {
            llm_provider_integration_id: "integration-1",
            model_identifier: "model-1",
          },
          settings: {
            context_window_tokens: null,
            max_output_tokens: null,
            builtin_tools: [],
          },
        },
      ],
      subagent_enabled: false,
      subagent_guidance: "Prefer for bounded investigation.",
    },
  ]);
});

void test("image generation model updates preserve unrelated built-in config keys", () => {
  const configured = {
    ...candidate("default-candidate"),
    builtin_tools: ["image_generation"],
    builtin_tool_configs: {
      image_generation: {
        quality: "high",
        model: "gpt-image-old",
      },
    },
  };

  const explicit = withImageGenerationModelIdentifier(
    configured,
    "gpt-image-current",
  );
  assert.equal(imageGenerationModelIdentifier(explicit), "gpt-image-current");
  assert.deepEqual(explicit.builtin_tool_configs.image_generation, {
    quality: "high",
    model: "gpt-image-current",
  });

  const maintainedDefault = withImageGenerationModelIdentifier(explicit, null);
  assert.equal(imageGenerationModelIdentifier(maintainedDefault), null);
  assert.deepEqual(maintainedDefault.builtin_tool_configs.image_generation, {
    quality: "high",
  });
});

void test("default-only image providers hide explicit model selection", () => {
  assert.equal(
    imageGenerationModelSelectionVisible({
      type: "UNSUPPORTED",
      data: {
        default_available: true,
        explicit_selection_supported: false,
        catalog_id: null,
        snapshot_id: null,
        snapshot_configuration_version: null,
        current_configuration_version: 1,
        snapshot_created_at: null,
        latest_attempt: null,
        stale: false,
        generation_current: true,
        sync_available_at: null,
        automatic_retry_blocked: false,
        entries: [],
        total: 0,
      },
    }),
    false,
  );
  assert.equal(imageGenerationModelSelectionVisible({ type: "LOADING" }), true);
});

void test("form serialization preserves complete built-in tool config", () => {
  const configured = {
    ...option("default", "default"),
    candidates: [
      {
        ...candidate("default-candidate"),
        model_selection_value: "integration-1:model-1",
        builtin_tools: ["image_generation"],
        builtin_tool_configs: {
          image_generation: {
            model: "gpt-image-current",
            quality: "high",
          },
        },
      },
    ],
  };

  const [input] = selectableModelOptionInputsFromFormValues([configured]);
  const settings = input?.candidates[0]?.settings;
  assert.ok(settings);
  assert.deepEqual(settings.builtin_tools, [
    {
      name: "image_generation",
      config: {
        model: "gpt-image-current",
        quality: "high",
      },
    },
  ]);
});

void test("form serialization preserves every ordered candidate", () => {
  const configured = {
    ...option("default", "default"),
    candidates: [
      {
        ...candidate("primary"),
        model_selection_value: "integration-1:model-primary",
      },
      {
        ...candidate("fallback"),
        model_selection_value: "integration-2:model-fallback",
        context_window_tokens: 64_000,
      },
    ],
  };

  const [input] = selectableModelOptionInputsFromFormValues([configured]);
  assert.deepEqual(
    input?.candidates.map((item) => ({
      ...item.model_selection,
      context_window_tokens: item.settings?.context_window_tokens ?? null,
    })),
    [
      {
        llm_provider_integration_id: "integration-1",
        model_identifier: "model-primary",
        context_window_tokens: null,
      },
      {
        llm_provider_integration_id: "integration-2",
        model_identifier: "model-fallback",
        context_window_tokens: 64_000,
      },
    ],
  );
});

void test("duplicate candidate validation is label-local", () => {
  const duplicated = {
    ...option("default", "default"),
    candidates: [
      {
        ...candidate("primary"),
        model_selection_value: "integration-1:model-1",
      },
      {
        ...candidate("fallback"),
        model_selection_value: "integration-1:model-1",
      },
    ],
  };
  const separateLabel = {
    ...option("secondary", "secondary"),
    candidates: [
      {
        ...candidate("secondary-primary"),
        model_selection_value: "integration-1:model-1",
      },
    ],
  };

  assert.equal(hasDuplicateSelectableModelCandidates([duplicated]), true);
  const uniqueCandidate = duplicated.candidates[0];
  assert.ok(uniqueCandidate);
  assert.equal(
    hasDuplicateSelectableModelCandidates([
      { ...duplicated, candidates: [uniqueCandidate] },
      separateLabel,
    ]),
    false,
  );
});

void test("Primary settings copy keeps only target-compatible values", () => {
  const primary = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-primary",
    context_window_tokens: 128_000,
    max_output_tokens: 16_000,
    builtin_tools: ["web_search", "image_generation"],
    builtin_tool_configs: {
      web_search: { depth: "high" },
      image_generation: { model: "gpt-image-current" },
    },
  };
  const target = {
    ...candidate("fallback"),
    model_provider_integration_id: "integration-fallback",
    normalized_capabilities: {
      reasoning: { supported: false, effort_levels: [] },
      built_in_tools: { supported: ["web_search"] },
      context_window: {
        max_input_tokens: 64_000,
        max_output_tokens: 32_000,
      },
      modalities: { input: ["text"], output: ["text"] },
      tool_calling: { supported: true },
      parameters: {},
      compatibility: {},
    } satisfies ModelCapabilities,
  };

  const copied = copyCompatiblePrimarySettings(primary, target);

  assert.equal(copied.candidate.context_window_tokens, null);
  assert.equal(copied.candidate.max_output_tokens, 16_000);
  assert.deepEqual(copied.candidate.builtin_tools, ["web_search"]);
  assert.deepEqual(copied.candidate.builtin_tool_configs, { web_search: {} });
  assert.deepEqual(copied.omitted, [
    "context_window",
    "builtin_tools",
    "builtin_tool_configs",
  ]);
});

void test("Primary settings copy preserves configs within one integration", () => {
  const primary = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-shared",
    builtin_tools: ["image_generation"],
    builtin_tool_configs: {
      image_generation: { model: "gpt-image-current" },
    },
  };
  const target = {
    ...candidate("fallback"),
    model_provider_integration_id: "integration-shared",
    normalized_capabilities: {
      reasoning: { supported: false, effort_levels: [] },
      built_in_tools: { supported: ["image_generation"] },
      context_window: {
        max_input_tokens: 64_000,
        max_output_tokens: 32_000,
      },
      modalities: { input: ["text"], output: ["text"] },
      tool_calling: { supported: true },
      parameters: {},
      compatibility: {},
    } satisfies ModelCapabilities,
  };

  const copied = copyCompatiblePrimarySettings(primary, target);

  assert.deepEqual(copied.candidate.builtin_tool_configs, {
    image_generation: { model: "gpt-image-current" },
  });
  assert.deepEqual(copied.omitted, []);
});

void test("Primary settings copy resets pinned image config across integrations", () => {
  const primary = {
    ...candidate("primary"),
    model_provider_integration_id: "integration-primary",
    builtin_tools: ["image_generation"],
    builtin_tool_configs: {
      image_generation: { model: "gpt-image-primary", quality: "high" },
    },
  };
  const target = {
    ...candidate("fallback"),
    model_provider_integration_id: "integration-fallback",
    normalized_capabilities: {
      reasoning: { supported: false, effort_levels: [] },
      built_in_tools: { supported: ["image_generation"] },
      context_window: {
        max_input_tokens: 64_000,
        max_output_tokens: 32_000,
      },
      modalities: { input: ["text"], output: ["text"] },
      tool_calling: { supported: true },
      parameters: {},
      compatibility: {},
    } satisfies ModelCapabilities,
  };

  const copied = copyCompatiblePrimarySettings(primary, target);

  assert.deepEqual(copied.candidate.builtin_tool_configs, {
    image_generation: {},
  });
  assert.deepEqual(copied.omitted, ["builtin_tool_configs"]);
});

void test("explicit image selection is invalid until a current catalog authorizes it", () => {
  const configured = {
    ...option("default", "default"),
    candidates: [
      {
        ...candidate("default-candidate"),
        model_provider_integration_id: "integration-1",
        builtin_tools: ["image_generation"],
        builtin_tool_configs: {
          image_generation: { model: "gpt-image-current" },
        },
      },
    ],
  };

  assert.equal(
    hasInvalidImageGenerationSelections(
      [configured],
      new Map([["integration-1", { type: "LOADING" }]]),
    ),
    true,
  );
  assert.equal(
    hasInvalidImageGenerationSelections(
      [configured],
      new Map([
        [
          "integration-1",
          {
            type: "LOADED",
            data: {
              default_available: true,
              explicit_selection_supported: true,
              catalog_id: "catalog-1",
              snapshot_id: "snapshot-1",
              snapshot_configuration_version: 1,
              current_configuration_version: 1,
              snapshot_created_at: "2026-09-10T00:00:00Z",
              latest_attempt: null,
              stale: false,
              generation_current: true,
              sync_available_at: null,
              automatic_retry_blocked: false,
              entries: [
                {
                  id: "entry-1",
                  provider: "openai",
                  provider_model_identifier: "gpt-image-current",
                  display_name: "Current Image Model",
                  description: "Current image model.",
                  recommendation_rank: 1,
                  lifecycle_status: "active",
                  visibility_status: "selectable",
                  source_metadata: null,
                  projection_metadata: null,
                },
              ],
              total: 1,
            },
          },
        ],
      ]),
    ),
    false,
  );
});

void test("subagent guidance is bounded to 500 characters", () => {
  assert.equal(isSubagentGuidanceWithinLimit("x".repeat(500)), true);
  assert.equal(isSubagentGuidanceWithinLimit("x".repeat(501)), false);
  assert.equal(isSubagentGuidanceWithinLimit(null), true);
});

void test("model context range preserves distinct default and maximum values", () => {
  assert.deepEqual(
    resolveModelContextRange({
      default_input_tokens: 272_000,
      max_input_tokens: 872_000,
    }),
    {
      defaultInputTokens: 272_000,
      maxInputTokens: 872_000,
    },
  );
});

void test("model context range treats a legacy maximum as the default", () => {
  assert.deepEqual(
    resolveModelContextRange({
      max_input_tokens: 128_000,
    }),
    {
      defaultInputTokens: 128_000,
      maxInputTokens: 128_000,
    },
  );
});

void test("model context range clamps an inconsistent default to the maximum", () => {
  assert.deepEqual(
    resolveModelContextRange({
      default_input_tokens: 272_000,
      max_input_tokens: 128_000,
    }),
    {
      defaultInputTokens: 128_000,
      maxInputTokens: 128_000,
    },
  );
});

void test("model context badge distinguishes a range from a legacy single value", () => {
  assert.deepEqual(
    modelContextBadgeValue({
      default_input_tokens: 272_000,
      max_input_tokens: 872_000,
    }),
    {
      type: "RANGE",
      defaultTokens: 272,
      maxTokens: 872,
    },
  );
  assert.deepEqual(
    modelContextBadgeValue({
      max_input_tokens: 128_000,
    }),
    {
      type: "SINGLE",
      tokens: 128,
    },
  );
  assert.deepEqual(
    modelContextBadgeValue({
      default_input_tokens: 272_000,
      max_input_tokens: 128_000,
    }),
    {
      type: "SINGLE",
      tokens: 128,
    },
  );
});
