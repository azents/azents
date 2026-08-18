import { isRecord, isString } from "../../shared/lib/unknown-value.ts";
import type { RequestedInferenceProfile } from "@azents/public-client";

export function normalizeStoredInferenceProfile(
  value: unknown,
): RequestedInferenceProfile | null {
  if (
    !isRecord(value) ||
    !isString(value.model_target_label) ||
    value.model_target_label.length === 0 ||
    !("reasoning_effort" in value)
  ) {
    return null;
  }
  const reasoningEffort = value.reasoning_effort;
  if (reasoningEffort !== null && !isString(reasoningEffort)) {
    return null;
  }
  return {
    model_target_label: value.model_target_label,
    reasoning_effort: reasoningEffort,
  };
}
