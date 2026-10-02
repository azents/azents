import type {
  CapabilitySupport,
  ModelCapabilities,
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

/** Synthetic evidence fixtures exercise contracts without claiming provider facts. */
export const partialReasoningCapabilities: ModelCapabilities = {
  context_window: { max_input_tokens: 128_000, max_output_tokens: 32_000 },
  reasoning: { supported: true, effort_levels: ["xhigh", "max"] },
  built_in_tools: { supported: ["web_search"] },
  tool_calling: { supported: false },
  semantic_contract: {
    version: 2,
    reasoning: {
      support: supported,
      completeness: "partial",
      efforts: [
        { level: "xhigh", state: "supported", origin: "explicit" },
        { level: "max", state: "supported", origin: "explicit" },
      ],
      default_effort: null,
    },
    reasoning_summaries: unknown,
    function_calling: unknown,
    parallel_function_calls: unknown,
    strict_function_schema: unknown,
    structured_response: unknown,
    parameters: {
      temperature: unknown,
      max_output_tokens: supported,
      top_p: unknown,
      top_k: unknown,
      stop_sequences: unknown,
    },
    input_modalities: [{ modality: "text", support: supported }],
    output_modalities: [{ modality: "text", support: supported }],
    built_in_tools: [
      { tool: "web_search", support: supported },
      {
        tool: "image_generation",
        support: {
          state: "conditional",
          origin: "explicit",
          predicate: { reasoning_efforts: ["max"], function_tools: null },
        },
      },
    ],
  },
};
