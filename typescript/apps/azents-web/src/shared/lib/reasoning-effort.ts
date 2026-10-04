import { z } from "zod/v4";
import type {
  ModelCapabilities,
  ModelReasoningEffort,
} from "@azents/public-client";

const DOMAIN_REASONING_EFFORTS = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
] as const;

/** Original seven-level domain. Raw provider labels outside this list are not selectable. */
export const REASONING_EFFORT_ORDER: readonly ModelReasoningEffort[] =
  DOMAIN_REASONING_EFFORTS;

/** Closed validation set shared by Agent, model-setting, and chat effort inputs. */
export const reasoningEffortInputSchema = z.enum(DOMAIN_REASONING_EFFORTS);

/** Accept only the original domain. Unknown raw labels, including observed ultra, are not selected. */
export function knownReasoningEffort(
  value: string | null,
): ModelReasoningEffort | null {
  switch (value) {
    case "none":
    case "minimal":
    case "low":
    case "medium":
    case "high":
    case "xhigh":
    case "max":
      return value;
    default:
      return null;
  }
}

/** Model configuration exposes the exact final effort set, not a partial request. */
export function reasoningEffortLevels(
  capabilities?: ModelCapabilities | null,
): ModelReasoningEffort[] {
  return capabilities?.reasoning?.supported
    ? [...(capabilities.reasoning.effort_levels ?? [])]
    : [];
}

/** Preserve explicit omission; normalize concrete model-change intent as before. */
export function normalizeReasoningEffortForCapabilities(
  effort: ModelReasoningEffort | null,
  capabilities?: ModelCapabilities | null,
): ModelReasoningEffort | null {
  return effort === null
    ? null
    : normalizeReasoningEffort(effort, reasoningEffortLevels(capabilities));
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
