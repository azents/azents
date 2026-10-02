import { capabilitySupportEnabled } from "./model-capability-support.ts";
import type {
  ModelCapabilities,
  ModelReasoningEffort,
} from "@azents/public-client";

export const REASONING_EFFORT_ORDER: readonly ModelReasoningEffort[] = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
];

export function reasoningEffortLevels(
  capabilities?: ModelCapabilities | null,
): ModelReasoningEffort[] {
  const contract = capabilities?.semantic_contract;
  if (contract != null) {
    return contract.reasoning.efforts
      .filter(
        (declaration) =>
          declaration.state === "supported" &&
          capabilitySupportEnabled(contract.reasoning.support, capabilities, {
            reasoningEffort: declaration.level,
          }),
      )
      .map((declaration) => declaration.level);
  }
  const reasoning = capabilities?.reasoning;
  if (!reasoning?.supported) {
    return [];
  }
  return reasoning.effort_levels ?? [];
}

/** New contracts preserve explicit intent and omission for saved-contract validation. */
export function normalizeReasoningEffortForCapabilities(
  effort: ModelReasoningEffort | null,
  capabilities?: ModelCapabilities | null,
): ModelReasoningEffort | null {
  return capabilities?.semantic_contract == null
    ? normalizeReasoningEffort(effort, reasoningEffortLevels(capabilities))
    : effort;
}

export function normalizeReasoningEffort(
  effort: ModelReasoningEffort | null,
  supportedEfforts: readonly ModelReasoningEffort[],
): ModelReasoningEffort | null {
  if (supportedEfforts.length === 0) {
    return null;
  }

  const baseline = effort ?? "medium";
  if (supportedEfforts.includes(baseline)) {
    return baseline;
  }

  const baselineIndex = REASONING_EFFORT_ORDER.indexOf(baseline);
  for (let index = baselineIndex - 1; index >= 0; index -= 1) {
    const lowerEffort = REASONING_EFFORT_ORDER.at(index);
    if (lowerEffort != null && supportedEfforts.includes(lowerEffort)) {
      return lowerEffort;
    }
  }
  for (
    let index = baselineIndex + 1;
    index < REASONING_EFFORT_ORDER.length;
    index += 1
  ) {
    const higherEffort = REASONING_EFFORT_ORDER.at(index);
    if (higherEffort != null && supportedEfforts.includes(higherEffort)) {
      return higherEffort;
    }
  }
  return null;
}
