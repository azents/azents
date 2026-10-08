import type { ModelCapabilities } from "@azents/public-client";

/** Synthetic final support for configuration and actual-request condition tests. */
export const partialReasoningCapabilities: ModelCapabilities = {
  context_window: { max_input_tokens: 128_000, max_output_tokens: 32_000 },
  reasoning: {
    supported: true,
    effort_levels: ["xhigh", "max"],
    summaries: false,
  },
  built_in_tools: { supported: ["web_search", "image_generation"] },
  tool_calling: {
    supported: false,
    parallel_tool_calls: false,
    strict_json_schema: false,
  },
  structured_response: false,
  parameters: { max_output_tokens: true },
  modalities: { input: ["text"], output: ["text"] },
  request_constraints: {
    known_default: null,
    feature_conditions: [
      {
        feature: "builtin:image_generation",
        reasoning_efforts: ["max"],
        function_tools: false,
      },
    ],
  },
};
