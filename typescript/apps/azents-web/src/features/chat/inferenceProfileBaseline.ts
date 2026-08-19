import type { RequestedInferenceProfile } from "@azents/public-client";

/**
 * Resolve the composer baseline without normalizing an explicitly applied Session profile.
 * A non-null applied profile remains authoritative even when its model label is no longer
 * present in the current Agent options; null inherits the current Agent fallback.
 */
export function resolveAppliedInferenceProfile(
  appliedProfile: RequestedInferenceProfile | null,
  fallbackProfile: RequestedInferenceProfile,
): RequestedInferenceProfile {
  return appliedProfile ?? fallbackProfile;
}
