import type {
  RuntimeExecutionManagementCapabilitiesResponse,
  RuntimeExecutionNetworkMode,
  RuntimeExecutionPolicyDocument,
  RuntimeExecutionStorageMode,
} from "@azents/admin-client";

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

export function isSupportedRuntimeExecutionStorageMode(
  value: string,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): value is RuntimeExecutionStorageMode {
  return capabilities.storage_modes.some((mode) => mode === value);
}

export function isSupportedRuntimeExecutionNetworkMode(
  value: string,
  capabilities: RuntimeExecutionManagementCapabilitiesResponse,
): value is RuntimeExecutionNetworkMode {
  return capabilities.network_modes.some((mode) => mode === value);
}
