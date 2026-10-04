import type {
  CapabilitySupport,
  ModelCapabilities,
  ModelReasoningEffort,
} from "@azents/public-client";

export interface CapabilityRequestContext {
  reasoningEffort?: ModelReasoningEffort | null;
  functionTools?: boolean | null;
}

/** Evaluate only saved evidence; unknown request dimensions cannot prove a condition. */
export function capabilitySupportEnabled(
  support: CapabilitySupport,
  capabilities?: ModelCapabilities | null,
  request: CapabilityRequestContext = {},
): boolean {
  if (support.state === "supported") {
    return true;
  }
  if (support.state !== "conditional" || support.predicate === null) {
    return false;
  }
  const effort =
    request.reasoningEffort ??
    capabilities?.semantic_contract?.reasoning.default_effort?.level ??
    null;
  const predicate = support.predicate;
  return (
    (predicate.reasoning_efforts === null ||
      (effort !== null && predicate.reasoning_efforts.includes(effort))) &&
    (predicate.function_tools === null ||
      predicate.function_tools === request.functionTools)
  );
}

export function supportedBuiltinTools(
  capabilities?: ModelCapabilities | null,
  request: CapabilityRequestContext = {},
): string[] {
  const contract = capabilities?.semantic_contract;
  if (contract == null) {
    return capabilities?.built_in_tools?.supported ?? [];
  }
  return contract.built_in_tools
    .filter((item) =>
      capabilitySupportEnabled(item.support, capabilities, request),
    )
    .map((item) => item.tool);
}

export function modelSupportsReasoning(
  capabilities: ModelCapabilities,
  request: CapabilityRequestContext = {},
): boolean {
  const contract = capabilities.semantic_contract;
  return contract == null
    ? (capabilities.reasoning?.supported ?? false)
    : capabilitySupportEnabled(
        contract.reasoning.support,
        capabilities,
        request,
      );
}

export function modelSupportsFunctionCalling(
  capabilities: ModelCapabilities,
  request: CapabilityRequestContext = {},
): boolean {
  const contract = capabilities.semantic_contract;
  return contract == null
    ? (capabilities.tool_calling?.supported ?? false)
    : capabilitySupportEnabled(
        contract.function_calling,
        capabilities,
        request,
      );
}

/** Picker status preserves uncertainty without authorizing unknown capabilities. */
export function modelFunctionCallingStatus(
  capabilities: ModelCapabilities,
  request: CapabilityRequestContext = {},
): "supported" | "unverified" | "hidden" {
  if (capabilities.semantic_contract?.function_calling.state === "unknown") {
    return "unverified";
  }
  return modelSupportsFunctionCalling(capabilities, request)
    ? "supported"
    : "hidden";
}
