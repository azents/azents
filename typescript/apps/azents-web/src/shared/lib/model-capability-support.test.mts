import assert from "node:assert/strict";
import test from "node:test";
import {
  capabilitySupportEnabled,
  modelFunctionCallingStatus,
  modelSupportsFunctionCalling,
  modelSupportsReasoning,
  supportedBuiltinTools,
} from "./model-capability-support.ts";
import {
  normalizeReasoningEffortForCapabilities,
  reasoningEffortLevels,
} from "./reasoning-effort.ts";
import type {
  CapabilitySupport,
  ModelCapabilities,
  ReasoningSupport,
} from "@azents/public-client";

const unknown: CapabilitySupport = {
  state: "unknown",
  origin: null,
  predicate: null,
};
const supported: CapabilitySupport = {
  state: "supported",
  origin: "explicit",
  predicate: null,
};
const unsupported: CapabilitySupport = {
  state: "unsupported",
  origin: "explicit",
  predicate: null,
};

function capabilities(
  reasoning: Partial<ReasoningSupport> = {},
): ModelCapabilities {
  return {
    // Stale derived views must not override a present versioned descriptor.
    reasoning: { supported: true, effort_levels: ["low", "medium", "high"] },
    built_in_tools: { supported: ["web_search", "image_generation"] },
    tool_calling: { supported: true },
    semantic_contract: {
      version: 2,
      reasoning: {
        support: unknown,
        completeness: "unknown",
        efforts: [],
        default_effort: null,
        ...reasoning,
      },
      reasoning_summaries: unknown,
      function_calling: unknown,
      parallel_function_calls: unknown,
      strict_function_schema: unknown,
      structured_response: unknown,
      parameters: {
        temperature: unknown,
        max_output_tokens: unknown,
        top_p: unknown,
        top_k: unknown,
        stop_sequences: unknown,
      },
      input_modalities: [],
      output_modalities: [],
      built_in_tools: [],
    },
  };
}

void test("v2 unknown support remains conservative despite old boolean views", () => {
  const model = capabilities();
  assert.deepEqual(reasoningEffortLevels(model), []);
  assert.deepEqual(supportedBuiltinTools(model), []);
  assert.equal(modelSupportsReasoning(model), false);
  assert.equal(modelSupportsFunctionCalling(model), false);
  assert.equal(capabilitySupportEnabled(unknown, model), false);
  assert.equal(capabilitySupportEnabled(unsupported, model), false);
  assert.equal(capabilitySupportEnabled(supported, model), true);
});

void test("function-calling status exposes unknown despite contradictory derived booleans", () => {
  for (const derived of [false, true]) {
    const model = capabilities();
    model.tool_calling = { supported: derived };
    assert.equal(modelFunctionCallingStatus(model), "unverified");
    assert.equal(modelSupportsFunctionCalling(model), false);
    assert.equal(capabilitySupportEnabled(unknown, model), false);
  }
});

void test("function-calling status uses v2 support and denial over stale views", () => {
  const model = capabilities();
  const descriptor = model.semantic_contract;
  assert.ok(descriptor);
  model.tool_calling = { supported: false };
  descriptor.function_calling = supported;
  assert.equal(modelFunctionCallingStatus(model), "supported");
  model.tool_calling = { supported: true };
  descriptor.function_calling = unsupported;
  assert.equal(modelFunctionCallingStatus(model), "hidden");
});

void test("function-calling status keeps unmet conditions hidden", () => {
  const model = capabilities();
  const descriptor = model.semantic_contract;
  assert.ok(descriptor);
  descriptor.function_calling = {
    state: "conditional",
    origin: "explicit",
    predicate: { reasoning_efforts: ["none"], function_tools: false },
  };
  assert.equal(modelFunctionCallingStatus(model), "hidden");
  assert.equal(
    modelFunctionCallingStatus(model, { reasoningEffort: "none" }),
    "hidden",
  );
  assert.equal(
    modelFunctionCallingStatus(model, {
      reasoningEffort: "none",
      functionTools: true,
    }),
    "hidden",
  );
  assert.equal(
    modelFunctionCallingStatus(model, {
      reasoningEffort: "none",
      functionTools: false,
    }),
    "supported",
  );
});

void test("function-calling status preserves descriptor-absent legacy behavior", () => {
  for (const semantic_contract of [null, void 0]) {
    assert.equal(
      modelFunctionCallingStatus({
        semantic_contract,
        tool_calling: { supported: true },
      }),
      "supported",
    );
    assert.equal(
      modelFunctionCallingStatus({
        semantic_contract,
        tool_calling: { supported: false },
      }),
      "hidden",
    );
    assert.equal(modelFunctionCallingStatus({ semantic_contract }), "hidden");
  }
});

void test("partial declarations expose only the exact justified subset including max/xhigh", () => {
  const model = capabilities({
    support: supported,
    completeness: "partial",
    efforts: [
      { level: "xhigh", state: "supported", origin: "explicit" },
      { level: "max", state: "supported", origin: "explicit" },
      { level: "low", state: "unsupported", origin: "explicit" },
      { level: "high", state: "unknown", origin: null },
    ],
  });
  assert.deepEqual(reasoningEffortLevels(model), ["xhigh", "max"]);
  assert.equal(normalizeReasoningEffortForCapabilities("max", model), "max");
  assert.equal(normalizeReasoningEffortForCapabilities("low", model), "low");
  assert.equal(normalizeReasoningEffortForCapabilities(null, model), null);
});

void test("known defaults are used only to evaluate predicates, not to overwrite omission", () => {
  const model = capabilities({
    support: supported,
    completeness: "partial",
    efforts: [{ level: "high", state: "supported", origin: "explicit" }],
    default_effort: { level: "high", origin: "explicit" },
  });
  const conditional: CapabilitySupport = {
    state: "conditional",
    origin: "contract_derived",
    predicate: { reasoning_efforts: ["high"], function_tools: null },
  };
  assert.equal(capabilitySupportEnabled(conditional, model), true);
  assert.equal(
    capabilitySupportEnabled(conditional, model, { reasoningEffort: "none" }),
    false,
  );
  assert.equal(normalizeReasoningEffortForCapabilities(null, model), null);
  assert.equal(
    normalizeReasoningEffortForCapabilities("xhigh", model),
    "xhigh",
  );
  assert.equal(capabilitySupportEnabled(conditional, capabilities()), false);
});

void test("conditional support requires every request dimension to be known and match", () => {
  const model = capabilities();
  const conditional: CapabilitySupport = {
    state: "conditional",
    origin: "explicit",
    predicate: { reasoning_efforts: ["none"], function_tools: false },
  };
  assert.equal(capabilitySupportEnabled(conditional, model), false);
  assert.equal(
    capabilitySupportEnabled(conditional, model, { reasoningEffort: "none" }),
    false,
  );
  assert.equal(
    capabilitySupportEnabled(conditional, model, {
      reasoningEffort: "none",
      functionTools: true,
    }),
    false,
  );
  assert.equal(
    capabilitySupportEnabled(conditional, model, {
      reasoningEffort: "none",
      functionTools: false,
    }),
    true,
  );
});

void test("conditional tools and reasoning use evidence rather than generic list defaults", () => {
  const model = capabilities();
  const contract = model.semantic_contract;
  assert.ok(contract);
  const conditional: CapabilitySupport = {
    state: "conditional",
    origin: "explicit",
    predicate: { reasoning_efforts: ["none"], function_tools: null },
  };
  contract.built_in_tools = [
    { tool: "image_generation", support: conditional },
    { tool: "web_search", support: unknown },
  ];
  contract.reasoning = {
    support: conditional,
    completeness: "partial",
    efforts: [
      { level: "none", state: "supported", origin: "explicit" },
      { level: "high", state: "supported", origin: "explicit" },
    ],
    default_effort: null,
  };
  assert.deepEqual(reasoningEffortLevels(model), ["none"]);
  assert.deepEqual(supportedBuiltinTools(model), []);
  assert.deepEqual(supportedBuiltinTools(model, { reasoningEffort: "none" }), [
    "image_generation",
  ]);
  assert.deepEqual(
    supportedBuiltinTools(model, { reasoningEffort: "high" }),
    [],
  );
});

void test("historical absent and null descriptors retain old effort normalization and tools", () => {
  for (const model of [
    {
      reasoning: { supported: true, effort_levels: ["low", "high"] },
      built_in_tools: { supported: ["code_execution", "web_search"] },
      tool_calling: { supported: true },
    },
    {
      reasoning: { supported: true, effort_levels: ["low", "high"] },
      built_in_tools: { supported: ["code_execution", "web_search"] },
      tool_calling: { supported: true },
      semantic_contract: null,
    },
  ] satisfies ModelCapabilities[]) {
    assert.deepEqual(reasoningEffortLevels(model), ["low", "high"]);
    assert.equal(normalizeReasoningEffortForCapabilities(null, model), "low");
    assert.equal(normalizeReasoningEffortForCapabilities("max", model), "high");
    assert.deepEqual(supportedBuiltinTools(model), [
      "code_execution",
      "web_search",
    ]);
    assert.equal(modelSupportsFunctionCalling(model), true);
    assert.equal(modelSupportsReasoning(model), true);
  }
  assert.equal(normalizeReasoningEffortForCapabilities("max", null), null);
  assert.deepEqual(supportedBuiltinTools(null), []);
});
