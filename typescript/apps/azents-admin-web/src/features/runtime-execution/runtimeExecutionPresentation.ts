import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionNetworkMode,
  RuntimeExecutionPolicyDocument,
} from "@azents/admin-client";

export type RuntimeExecutionDockerCapability =
  | "image_build"
  | "container_run"
  | "compose";

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

export function getRuntimeExecutionPolicyIssue(
  policy: RuntimeExecutionPolicyDocument,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): string | null {
  if (!isRuntimeExecutionPolicySupported(policy, capabilities)) {
    return "This Profile uses a capability that the current Runtime Provider does not support.";
  }
  if (policy.compose.enabled && !policy.container_run.enabled) {
    return "Docker Compose requires Docker container execution.";
  }
  const dockerEnabled =
    policy.image_build.enabled || policy.container_run.enabled;
  if (!dockerEnabled) {
    return null;
  }
  if (
    policy.engine_storage.mode !== "ephemeral" ||
    policy.engine_storage.capacity_bytes === null ||
    policy.engine_storage.capacity_bytes < 1
  ) {
    return "Enter a temporary Docker storage capacity before saving.";
  }
  const resources = policy.resources;
  if (
    [
      resources.cpu_millicores,
      resources.memory_bytes,
      resources.pids,
      resources.container_count,
      resources.ephemeral_storage_bytes,
    ].some((value) => value === null || value < 1)
  ) {
    return "Set every Runtime resource limit to a positive value before enabling Docker.";
  }
  return null;
}

export function isSupportedRuntimeExecutionNetworkMode(
  value: string,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): value is RuntimeExecutionNetworkMode {
  return capabilities.network_modes.some((mode) => mode === value);
}

export function updateRuntimeExecutionDockerCapability(
  policy: RuntimeExecutionPolicyDocument,
  capability: RuntimeExecutionDockerCapability,
  enabled: boolean,
): RuntimeExecutionPolicyDocument {
  const imageBuildEnabled =
    capability === "image_build" ? enabled : policy.image_build.enabled;
  const containerRunEnabled =
    capability === "container_run"
      ? enabled
      : capability === "compose" && enabled
        ? true
        : policy.container_run.enabled;
  const composeEnabled =
    capability === "compose"
      ? enabled
      : capability === "container_run" && !enabled
        ? false
        : policy.compose.enabled;
  const dockerEnabled = imageBuildEnabled || containerRunEnabled;

  return {
    ...policy,
    image_build: {
      ...policy.image_build,
      enabled: imageBuildEnabled,
    },
    container_run: {
      ...policy.container_run,
      enabled: containerRunEnabled,
    },
    compose: {
      ...policy.compose,
      enabled: composeEnabled,
    },
    engine_storage: {
      ...policy.engine_storage,
      mode: dockerEnabled ? "ephemeral" : "none",
      capacity_bytes: dockerEnabled
        ? policy.engine_storage.capacity_bytes
        : null,
    },
  };
}

export function updateRuntimeExecutionNetworkMode(
  policy: RuntimeExecutionPolicyDocument,
  mode: RuntimeExecutionNetworkMode,
): RuntimeExecutionPolicyDocument {
  return {
    ...policy,
    network_egress: {
      ...policy.network_egress,
      mode,
      allowed_destinations:
        mode === "restricted" ? policy.network_egress.allowed_destinations : [],
      denied_destinations:
        mode === "none" ? [] : policy.network_egress.denied_destinations,
    },
  };
}
