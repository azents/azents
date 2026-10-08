import type {
  ModelCapabilities,
  ModelCapabilityFeature,
  ModelReasoningEffort,
} from "@azents/public-client";

/**
 * Qualified reasoning state used to evaluate request conditions.
 *
 * Omission inherits a known default. An explicit effort, including literal
 * "none", stays exact. Cleared, budget, adaptive, and disabled states supply
 * no effort.
 */
export type CapabilityReasoningKind =
  | { kind: "omitted" }
  | { kind: "effort"; effort: ModelReasoningEffort }
  | { kind: "cleared" }
  | { kind: "budget" }
  | { kind: "adaptive" }
  | { kind: "disabled" };

/** Complete effective request context required by condition helpers. */
export interface CapabilityRequestContext {
  reasoning: CapabilityReasoningKind;
  functionTools: boolean;
}

/** Final membership is configuration potential, independent of request conditions. */
export function hasModelFeature(
  capabilities: ModelCapabilities | null,
  feature: ModelCapabilityFeature,
): boolean {
  if (capabilities === null) {
    return false;
  }
  switch (feature) {
    case "function_calling":
      return capabilities.tool_calling?.supported ?? false;
    case "parallel_function_calls":
      return capabilities.tool_calling?.parallel_tool_calls ?? false;
    case "strict_function_schema":
      return capabilities.tool_calling?.strict_json_schema ?? false;
    case "structured_response":
      return capabilities.structured_response ?? false;
    case "reasoning":
      return capabilities.reasoning?.supported ?? false;
    case "reasoning_summaries":
      return capabilities.reasoning?.summaries ?? false;
    case "temperature":
    case "max_output_tokens":
    case "top_p":
    case "top_k":
    case "stop_sequences":
      return capabilities.parameters?.[feature] ?? false;
    case "input:text":
      return capabilities.modalities?.input?.includes("text") ?? false;
    case "input:image":
      return capabilities.modalities?.input?.includes("image") ?? false;
    case "input:pdf":
      return capabilities.modalities?.input?.includes("pdf") ?? false;
    case "input:audio":
      return capabilities.modalities?.input?.includes("audio") ?? false;
    case "input:video":
      return capabilities.modalities?.input?.includes("video") ?? false;
    case "output:text":
      return capabilities.modalities?.output?.includes("text") ?? false;
    case "output:image":
      return capabilities.modalities?.output?.includes("image") ?? false;
    case "output:pdf":
      return capabilities.modalities?.output?.includes("pdf") ?? false;
    case "output:audio":
      return capabilities.modalities?.output?.includes("audio") ?? false;
    case "output:video":
      return capabilities.modalities?.output?.includes("video") ?? false;
    case "builtin:web_search":
      return (
        capabilities.built_in_tools?.supported?.includes("web_search") ?? false
      );
    case "builtin:image_generation":
      return (
        capabilities.built_in_tools?.supported?.includes("image_generation") ??
        false
      );
    default: {
      const unreachable: never = feature;
      return unreachable;
    }
  }
}

/** Conditions constrain a present feature against the complete effective request. */
export function modelFeatureEnabled(
  capabilities: ModelCapabilities | null,
  feature: ModelCapabilityFeature,
  request: CapabilityRequestContext,
): boolean {
  if (!hasModelFeature(capabilities, feature)) {
    return false;
  }
  const constraints = capabilities?.request_constraints;
  const condition = constraints?.feature_conditions?.find(
    (item) => item.feature === feature,
  );
  if (condition == null) {
    return true;
  }
  const effort = conditionEffort(
    request.reasoning,
    constraints?.known_default ?? null,
  );
  return (
    (condition.reasoning_efforts === null ||
      (effort !== null && condition.reasoning_efforts.includes(effort))) &&
    (condition.function_tools === null ||
      condition.function_tools === request.functionTools)
  );
}

function conditionEffort(
  reasoning: CapabilityReasoningKind,
  knownDefault: ModelReasoningEffort | null,
): ModelReasoningEffort | null {
  switch (reasoning.kind) {
    case "omitted":
      return knownDefault ?? null;
    case "effort":
      return reasoning.effort;
    case "cleared":
    case "budget":
    case "adaptive":
    case "disabled":
      return null;
    default: {
      const unreachable: never = reasoning;
      return unreachable;
    }
  }
}

/** Settings and picker consumers expose every final supported configurable tool. */
export function configurableBuiltinTools(
  capabilities?: ModelCapabilities | null,
): string[] {
  return [...(capabilities?.built_in_tools?.supported ?? [])];
}

/** Actual request consumers must supply complete function-tool and effort context. */
export function supportedBuiltinTools(
  capabilities: ModelCapabilities | null,
  request: CapabilityRequestContext,
): string[] {
  return configurableBuiltinTools(capabilities).filter((tool) => {
    switch (tool) {
      case "web_search":
        return modelFeatureEnabled(capabilities, "builtin:web_search", request);
      case "image_generation":
        return modelFeatureEnabled(
          capabilities,
          "builtin:image_generation",
          request,
        );
      default:
        // Other registered tools have no condition key in the current API contract.
        return true;
    }
  });
}

export function modelSupportsReasoning(
  capabilities: ModelCapabilities,
): boolean {
  return hasModelFeature(capabilities, "reasoning");
}

export function modelSupportsFunctionCalling(
  capabilities: ModelCapabilities,
): boolean {
  return hasModelFeature(capabilities, "function_calling");
}
