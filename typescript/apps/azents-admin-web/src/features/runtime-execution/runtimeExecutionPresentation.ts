import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionPolicyDocument,
} from "@azents/admin-client";

const DEFAULT_DOCKER_STORAGE_CAPACITY_BYTES = 16 * 1024 ** 3;
const DEFAULT_DOCKER_EPHEMERAL_STORAGE_BYTES = 16 * 1024 ** 3;

export function isRuntimeExecutionPolicySupported(
  policy: RuntimeExecutionPolicyDocument,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): boolean {
  return (
    (!policy.docker.enabled || capabilities.docker) &&
    capabilities.storage_modes.includes(policy.docker.storage_mode)
  );
}

export function getRuntimeExecutionPolicyIssue(
  policy: RuntimeExecutionPolicyDocument,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): string | null {
  if (!isRuntimeExecutionPolicySupported(policy, capabilities)) {
    return "This Profile uses a capability that the current Runtime Provider does not support.";
  }
  const resources = policy.resources;
  if (
    resources.cpu_request_millicores !== null &&
    resources.cpu_limit_millicores !== null &&
    resources.cpu_request_millicores > resources.cpu_limit_millicores
  ) {
    return "CPU request cannot exceed CPU limit.";
  }
  if (
    resources.memory_request_bytes !== null &&
    resources.memory_limit_bytes !== null &&
    resources.memory_request_bytes > resources.memory_limit_bytes
  ) {
    return "Memory request cannot exceed memory limit.";
  }
  if (!policy.docker.enabled) {
    return null;
  }
  if (
    policy.docker.storage_mode !== "ephemeral" ||
    policy.docker.storage_capacity_bytes === null
  ) {
    return "Enter a temporary Docker storage capacity before saving.";
  }
  if (resources.ephemeral_storage_bytes === null) {
    return "Set the Kubernetes ephemeral-storage value before enabling Docker.";
  }
  return null;
}

export function updateRuntimeExecutionDocker(
  policy: RuntimeExecutionPolicyDocument,
  enabled: boolean,
): RuntimeExecutionPolicyDocument {
  return {
    ...policy,
    docker: {
      ...policy.docker,
      enabled,
      storage_mode: enabled ? "ephemeral" : "none",
      storage_capacity_bytes: enabled
        ? (policy.docker.storage_capacity_bytes ??
          DEFAULT_DOCKER_STORAGE_CAPACITY_BYTES)
        : null,
    },
    resources: {
      ...policy.resources,
      cpu_request_millicores: enabled
        ? policy.resources.cpu_request_millicores
        : null,
      cpu_limit_millicores: enabled
        ? policy.resources.cpu_limit_millicores
        : null,
      memory_request_bytes: enabled
        ? policy.resources.memory_request_bytes
        : null,
      memory_limit_bytes: enabled ? policy.resources.memory_limit_bytes : null,
      ephemeral_storage_bytes: enabled
        ? (policy.resources.ephemeral_storage_bytes ??
          DEFAULT_DOCKER_EPHEMERAL_STORAGE_BYTES)
        : null,
    },
  };
}

export function withRuntimeExecutionDockerDefaults(
  policy: RuntimeExecutionPolicyDocument,
): RuntimeExecutionPolicyDocument {
  return policy.docker.enabled
    ? updateRuntimeExecutionDocker(policy, true)
    : policy;
}
