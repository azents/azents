import type {
  AgentRuntimeExecutionPolicyStatusResponse,
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionRequiredAction,
  WorkspaceRuntimeExecutionProfileResponse,
  WorkspaceUserRole,
} from "@azents/public-client";

export const RUNTIME_EXECUTION_STATUS_REFETCH_INTERVAL_MS = 2_000;

export function canEditWorkspaceRuntimeExecution(
  role: WorkspaceUserRole,
): boolean {
  return role === "owner" || role === "manager";
}

export function canApplyRuntimeExecution(
  requiredAction: RuntimeExecutionRequiredAction,
): boolean {
  return requiredAction === "apply";
}

export function isRuntimeExecutionPolicySupported(
  policy: RuntimeExecutionPolicyDocument,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): boolean {
  return (
    (!policy.image_build.enabled || capabilities.image_build) &&
    (!policy.container_run.enabled || capabilities.container_run) &&
    (!policy.compose.enabled || capabilities.compose) &&
    capabilities.storage_modes.includes(policy.engine_storage.mode) &&
    capabilities.network_modes.includes(policy.network_egress.mode)
  );
}

export function canAllowWorkspaceRuntimeExecutionProfile(
  profile: WorkspaceRuntimeExecutionProfileResponse,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): boolean {
  return (
    profile.lifecycle === "active" &&
    isRuntimeExecutionPolicySupported(profile.policy, capabilities)
  );
}

export function canSaveWorkspaceRuntimeExecution(
  allowedProfileIds: string[],
  profiles: WorkspaceRuntimeExecutionProfileResponse[],
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): boolean {
  return (
    allowedProfileIds.length > 0 &&
    allowedProfileIds.every((profileId) => {
      const profile = profiles.find((item) => item.id === profileId);
      if (!profile) {
        return false;
      }
      return canAllowWorkspaceRuntimeExecutionProfile(profile, capabilities);
    })
  );
}

export function canSelectAgentRuntimeExecutionProfile(
  profile: WorkspaceRuntimeExecutionProfileResponse,
): boolean {
  return profile.lifecycle === "active" && profile.available;
}

export function canSaveAgentRuntimeExecution(
  profileId: string | null,
  profiles: WorkspaceRuntimeExecutionProfileResponse[],
): boolean {
  if (profileId === null) {
    return false;
  }
  const profile = profiles.find((item) => item.id === profileId);
  if (!profile) {
    return false;
  }
  return canSelectAgentRuntimeExecutionProfile(profile);
}

export function runtimeExecutionStatusRefetchInterval(
  status?: AgentRuntimeExecutionPolicyStatusResponse,
): number | false {
  return status?.required_action === "wait"
    ? RUNTIME_EXECUTION_STATUS_REFETCH_INTERVAL_MS
    : false;
}
