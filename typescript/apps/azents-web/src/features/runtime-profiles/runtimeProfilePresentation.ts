export type RuntimeProfileAvailabilityReason =
  | "workspaceProfileDisabled"
  | "providerUnavailable"
  | "infrastructureProfileUnavailable"
  | "workspacePolicyInvalid"
  | "profileIncompatible"
  | "unknown";

export function runtimeProfileAvailabilityReason(
  reasonCode: string | null,
): RuntimeProfileAvailabilityReason {
  switch (reasonCode) {
    case "workspace_profile_disabled":
      return "workspaceProfileDisabled";
    case "provider_unavailable":
    case "provider_disabled":
    case "provider_not_active":
    case "provider_disconnected":
    case "provider_workspace_unavailable":
      return "providerUnavailable";
    case "infrastructure_profile_unavailable":
    case "infrastructure_profile_disabled":
      return "infrastructureProfileUnavailable";
    case "workspace_policy_invalid":
      return "workspacePolicyInvalid";
    case "provider_capability_missing":
    case "provider_capability_unavailable":
    case "profile_incompatible":
      return "profileIncompatible";
    default:
      return "unknown";
  }
}
