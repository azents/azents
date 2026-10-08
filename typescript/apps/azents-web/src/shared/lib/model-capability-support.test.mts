import assert from "node:assert/strict";
import test from "node:test";
import {
  type CapabilityRequestContext,
  configurableBuiltinTools,
  hasModelFeature,
  modelFeatureEnabled,
  modelSupportsFunctionCalling,
  modelSupportsReasoning,
  supportedBuiltinTools,
} from "./model-capability-support.ts";
import {
  normalizeReasoningEffortForCapabilities,
  reasoningEffortLevels,
} from "./reasoning-effort.ts";
import type {
  ModelCapabilities,
  ModelCapabilityFeature,
} from "@azents/public-client";

const FEATURES: readonly ModelCapabilityFeature[] = [
  "function_calling",
  "parallel_function_calls",
  "strict_function_schema",
  "structured_response",
  "reasoning",
  "reasoning_summaries",
  "temperature",
  "max_output_tokens",
  "top_p",
  "top_k",
  "stop_sequences",
  "input:text",
  "input:image",
  "input:pdf",
  "input:audio",
  "input:video",
  "output:text",
  "output:image",
  "output:pdf",
  "output:audio",
  "output:video",
  "builtin:web_search",
  "builtin:image_generation",
];

function fullCapabilities(): ModelCapabilities {
  return {
    tool_calling: {
      supported: true,
      parallel_tool_calls: true,
      strict_json_schema: true,
    },
    structured_response: true,
    reasoning: {
      supported: true,
      effort_levels: ["xhigh", "max"],
      summaries: true,
    },
    parameters: {
      temperature: true,
      max_output_tokens: true,
      top_p: true,
      top_k: true,
      stop_sequences: true,
    },
    modalities: {
      input: ["text", "image", "pdf", "audio", "video"],
      output: ["text", "image", "pdf", "audio", "video"],
    },
    built_in_tools: { supported: ["web_search", "image_generation"] },
    request_constraints: { known_default: null, feature_conditions: [] },
  };
}

const REQUEST: CapabilityRequestContext = {
  reasoning: { kind: "omitted" },
  functionTools: false,
};

function effortRequest(
  effort: "none" | "xhigh" | "max",
  functionTools: boolean,
): CapabilityRequestContext {
  return { reasoning: { kind: "effort", effort }, functionTools };
}

void test("feature accessors read their own flat field rather than a related support flag", () => {
  const isolated: Array<{
    feature: ModelCapabilityFeature;
    capabilities: ModelCapabilities;
  }> = [
    {
      feature: "function_calling",
      capabilities: { tool_calling: { supported: true } },
    },
    {
      feature: "parallel_function_calls",
      capabilities: { tool_calling: { parallel_tool_calls: true } },
    },
    {
      feature: "strict_function_schema",
      capabilities: { tool_calling: { strict_json_schema: true } },
    },
    {
      feature: "structured_response",
      capabilities: { structured_response: true },
    },
    { feature: "reasoning", capabilities: { reasoning: { supported: true } } },
    {
      feature: "reasoning_summaries",
      capabilities: { reasoning: { summaries: true } },
    },
    {
      feature: "temperature",
      capabilities: { parameters: { temperature: true } },
    },
    {
      feature: "max_output_tokens",
      capabilities: { parameters: { max_output_tokens: true } },
    },
    { feature: "top_p", capabilities: { parameters: { top_p: true } } },
    { feature: "top_k", capabilities: { parameters: { top_k: true } } },
    {
      feature: "stop_sequences",
      capabilities: { parameters: { stop_sequences: true } },
    },
    {
      feature: "input:text",
      capabilities: { modalities: { input: ["text"] } },
    },
    {
      feature: "input:image",
      capabilities: { modalities: { input: ["image"] } },
    },
    { feature: "input:pdf", capabilities: { modalities: { input: ["pdf"] } } },
    {
      feature: "input:audio",
      capabilities: { modalities: { input: ["audio"] } },
    },
    {
      feature: "input:video",
      capabilities: { modalities: { input: ["video"] } },
    },
    {
      feature: "output:text",
      capabilities: { modalities: { output: ["text"] } },
    },
    {
      feature: "output:image",
      capabilities: { modalities: { output: ["image"] } },
    },
    {
      feature: "output:pdf",
      capabilities: { modalities: { output: ["pdf"] } },
    },
    {
      feature: "output:audio",
      capabilities: { modalities: { output: ["audio"] } },
    },
    {
      feature: "output:video",
      capabilities: { modalities: { output: ["video"] } },
    },
    {
      feature: "builtin:web_search",
      capabilities: { built_in_tools: { supported: ["web_search"] } },
    },
    {
      feature: "builtin:image_generation",
      capabilities: { built_in_tools: { supported: ["image_generation"] } },
    },
  ];
  assert.deepEqual(
    isolated.map((item) => item.feature),
    FEATURES,
  );
  for (const item of isolated) {
    for (const feature of FEATURES) {
      assert.equal(
        hasModelFeature(item.capabilities, feature),
        feature === item.feature,
        `${item.feature} / ${feature}`,
      );
    }
  }
});

void test("all final feature fields determine membership and unconstrained request support", () => {
  const model = fullCapabilities();
  for (const feature of FEATURES) {
    assert.equal(hasModelFeature(model, feature), true, feature);
    assert.equal(modelFeatureEnabled(model, feature, REQUEST), true, feature);
    assert.equal(hasModelFeature({}, feature), false, feature);
    assert.equal(hasModelFeature(null, feature), false, feature);
    assert.equal(modelFeatureEnabled({}, feature, REQUEST), false, feature);
  }
  assert.equal(modelSupportsReasoning(model), true);
  assert.equal(modelSupportsFunctionCalling(model), true);
  assert.equal(modelSupportsReasoning({}), false);
  assert.equal(modelSupportsFunctionCalling({}), false);
});

void test("each request constraint affects execution without removing configuration potential", () => {
  for (const feature of FEATURES) {
    const model = fullCapabilities();
    model.request_constraints = {
      known_default: null,
      feature_conditions: [
        { feature, reasoning_efforts: ["max"], function_tools: false },
      ],
    };
    assert.equal(hasModelFeature(model, feature), true, feature);
    assert.equal(modelFeatureEnabled(model, feature, REQUEST), false, feature);
    assert.equal(
      modelFeatureEnabled(model, feature, effortRequest("max", false)),
      true,
      feature,
    );
    assert.equal(
      modelFeatureEnabled(model, feature, effortRequest("max", true)),
      false,
      feature,
    );
    assert.equal(
      modelFeatureEnabled(model, feature, effortRequest("xhigh", false)),
      false,
      feature,
    );
  }
});

void test("known defaults evaluate omission without replacing explicit actual effort", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: "max",
    feature_conditions: [
      {
        feature: "temperature",
        reasoning_efforts: ["max"],
        function_tools: null,
      },
    ],
  };
  assert.equal(modelFeatureEnabled(model, "temperature", REQUEST), true);
  assert.equal(
    modelFeatureEnabled(model, "temperature", effortRequest("none", false)),
    false,
  );
  assert.equal(
    modelFeatureEnabled(model, "temperature", effortRequest("xhigh", true)),
    false,
  );
  assert.deepEqual(reasoningEffortLevels(model), ["xhigh", "max"]);
});

void test("constraint dimensions are a conjunction of actual effort and function tools", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: null,
    feature_conditions: [
      {
        feature: "function_calling",
        reasoning_efforts: null,
        function_tools: true,
      },
      {
        feature: "structured_response",
        reasoning_efforts: ["none"],
        function_tools: false,
      },
    ],
  };
  assert.equal(modelFeatureEnabled(model, "function_calling", REQUEST), false);
  assert.equal(
    modelFeatureEnabled(model, "function_calling", {
      reasoning: { kind: "omitted" },
      functionTools: true,
    }),
    true,
  );
  assert.equal(
    modelFeatureEnabled(
      model,
      "structured_response",
      effortRequest("none", false),
    ),
    true,
  );
  assert.equal(
    modelFeatureEnabled(
      model,
      "structured_response",
      effortRequest("none", true),
    ),
    false,
  );
  assert.equal(
    modelFeatureEnabled(model, "structured_response", REQUEST),
    false,
  );
  // Display and model configuration reflect final membership, not current request use.
  assert.equal(modelSupportsFunctionCalling(model), true);
});

void test("conditional tool configuration stays intact while actual requests enforce conditions", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: null,
    feature_conditions: [
      {
        feature: "builtin:image_generation",
        reasoning_efforts: ["max"],
        function_tools: false,
      },
    ],
  };
  const before = JSON.stringify(model);
  assert.deepEqual(configurableBuiltinTools(model), [
    "web_search",
    "image_generation",
  ]);
  assert.deepEqual(supportedBuiltinTools(model, REQUEST), ["web_search"]);
  assert.deepEqual(supportedBuiltinTools(model, effortRequest("max", false)), [
    "web_search",
    "image_generation",
  ]);
  assert.deepEqual(supportedBuiltinTools(model, effortRequest("max", true)), [
    "web_search",
  ]);
  const tools = configurableBuiltinTools(model);
  tools.pop();
  assert.equal(JSON.stringify(model), before);
});

void test("constraints cannot authorize an absent final feature", () => {
  const model: ModelCapabilities = {
    tool_calling: { supported: false },
    request_constraints: {
      known_default: "max",
      feature_conditions: [
        {
          feature: "function_calling",
          reasoning_efforts: ["max"],
          function_tools: false,
        },
      ],
    },
  };
  assert.equal(hasModelFeature(model, "function_calling"), false);
  assert.equal(modelFeatureEnabled(model, "function_calling", REQUEST), false);
});

void test("flat historical reads need no alternate capability authority", () => {
  const model: ModelCapabilities = {
    reasoning: { supported: true, effort_levels: ["low", "high"] },
    built_in_tools: { supported: ["code_execution", "web_search"] },
    tool_calling: { supported: true },
  };
  assert.equal(modelSupportsFunctionCalling(model), true);
  assert.equal(modelFeatureEnabled(model, "function_calling", REQUEST), true);
  assert.deepEqual(configurableBuiltinTools(model), [
    "code_execution",
    "web_search",
  ]);
  assert.deepEqual(supportedBuiltinTools(model, REQUEST), [
    "code_execution",
    "web_search",
  ]);
  assert.deepEqual(reasoningEffortLevels(model), ["low", "high"]);
  assert.deepEqual(configurableBuiltinTools(null), []);
  assert.deepEqual(reasoningEffortLevels(null), []);
});

void test("final reasoning subset is never expanded or filtered using a partial request", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: null,
    feature_conditions: [
      {
        feature: "reasoning",
        reasoning_efforts: ["max"],
        function_tools: true,
      },
    ],
  };
  assert.deepEqual(reasoningEffortLevels(model), ["xhigh", "max"]);
  assert.equal(modelSupportsReasoning(model), true);
  assert.equal(modelFeatureEnabled(model, "reasoning", REQUEST), false);
});

void test("concrete effort adaptation preserves null, valid intent, and existing effort order", () => {
  const model = fullCapabilities();
  model.reasoning = { supported: true, effort_levels: ["low", "high"] };
  assert.equal(normalizeReasoningEffortForCapabilities(null, model), null);
  assert.equal(normalizeReasoningEffortForCapabilities("high", model), "high");
  assert.equal(normalizeReasoningEffortForCapabilities("medium", model), "low");
  assert.equal(
    normalizeReasoningEffortForCapabilities("minimal", model),
    "low",
  );
  assert.equal(normalizeReasoningEffortForCapabilities("max", model), "high");
  model.reasoning = { supported: false, effort_levels: [] };
  assert.equal(normalizeReasoningEffortForCapabilities("max", model), null);
  assert.equal(normalizeReasoningEffortForCapabilities(null, model), null);
});

void test("explicit cleared and budget do not inherit a known default", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: "max",
    feature_conditions: [
      {
        feature: "temperature",
        reasoning_efforts: ["max"],
        function_tools: null,
      },
    ],
  };
  const kinds = ["cleared", "budget", "adaptive", "disabled"] as const;
  for (const kind of kinds) {
    assert.equal(
      modelFeatureEnabled(model, "temperature", {
        reasoning: { kind },
        functionTools: false,
      }),
      false,
      kind,
    );
  }
  assert.equal(
    modelFeatureEnabled(model, "temperature", effortRequest("none", false)),
    false,
  );
  assert.equal(
    modelFeatureEnabled(model, "temperature", effortRequest("max", false)),
    true,
  );
});

void test("effort none stays exact and does not inherit a different known default", () => {
  const model = fullCapabilities();
  model.request_constraints = {
    known_default: "max",
    feature_conditions: [
      {
        feature: "temperature",
        reasoning_efforts: ["none"],
        function_tools: null,
      },
    ],
  };
  assert.equal(modelFeatureEnabled(model, "temperature", REQUEST), false);
  assert.equal(
    modelFeatureEnabled(model, "temperature", effortRequest("none", false)),
    true,
  );
  assert.equal(
    modelFeatureEnabled(model, "temperature", {
      reasoning: { kind: "cleared" },
      functionTools: false,
    }),
    false,
  );
  assert.equal(
    modelFeatureEnabled(model, "temperature", {
      reasoning: { kind: "budget" },
      functionTools: false,
    }),
    false,
  );
});
