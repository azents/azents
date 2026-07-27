import type {
  AgentRuntimeExecutionPolicyStatusResponse,
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionRequiredAction,
  WorkspaceRuntimeExecutionProfileResponse,
  WorkspaceUserRole,
} from "@azents/public-client";

export const RUNTIME_EXECUTION_STATUS_REFETCH_INTERVAL_MS = 2_000;

const RUNTIME_POLICY_REASON_MESSAGE_KEYS = {
  profile_retired: "reasonExplanations.profile_retired",
  profile_not_allowed: "reasonExplanations.profile_not_allowed",
  dependency_unsatisfied: "reasonExplanations.dependency_unsatisfied",
  provider_module_unsupported: "reasonExplanations.provider_module_unsupported",
  provider_engine_unsupported: "reasonExplanations.provider_engine_unsupported",
  provider_storage_unsupported:
    "reasonExplanations.provider_storage_unsupported",
  provider_network_unsupported:
    "reasonExplanations.provider_network_unsupported",
  provider_limit_exceeded: "reasonExplanations.provider_limit_exceeded",
  execution_policy_unavailable:
    "reasonExplanations.execution_policy_unavailable",
  automatic_convergence_pending:
    "reasonExplanations.automatic_convergence_pending",
  explicit_apply_required: "reasonExplanations.explicit_apply_required",
  application_pending: "reasonExplanations.application_pending",
  target_divergent: "reasonExplanations.target_divergent",
  reported_digest_mismatch: "reasonExplanations.reported_digest_mismatch",
  target_generation_mismatch: "reasonExplanations.target_generation_mismatch",
  applied_snapshot_missing: "reasonExplanations.applied_snapshot_missing",
  applied_snapshot_unverified: "reasonExplanations.applied_snapshot_unverified",
  applied_pointer_mismatch: "reasonExplanations.applied_pointer_mismatch",
  RUNTIME_POLICY_PROVIDER_EVIDENCE_MISMATCH:
    "reasonExplanations.provider_evidence_mismatch",
} as const;

type RuntimePolicyReasonMessageKey =
  | (typeof RUNTIME_POLICY_REASON_MESSAGE_KEYS)[keyof typeof RUNTIME_POLICY_REASON_MESSAGE_KEYS]
  | "reasonExplanations.runtime_failure";

export function runtimePolicyReasonMessageKey(
  reason: string,
): RuntimePolicyReasonMessageKey {
  if (reason in RUNTIME_POLICY_REASON_MESSAGE_KEYS) {
    return RUNTIME_POLICY_REASON_MESSAGE_KEYS[
      reason as keyof typeof RUNTIME_POLICY_REASON_MESSAGE_KEYS
    ];
  }
  return "reasonExplanations.runtime_failure";
}

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
