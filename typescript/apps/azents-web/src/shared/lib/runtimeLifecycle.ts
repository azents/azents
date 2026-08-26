import type {
  AgentRuntimeLifecyclePresentationResponse,
  AgentWorkspaceResponse,
  RuntimeConfigurationStatus,
} from "@azents/public-client";

export function shouldPollRuntimeLifecycle(
  lifecycle?: AgentRuntimeLifecyclePresentationResponse | null,
  options?: {
    removing?: boolean;
    configurationStatus?: RuntimeConfigurationStatus | null;
  },
): boolean {
  return (
    options?.removing === true ||
    options?.configurationStatus === "waiting_for_recreation" ||
    (lifecycle ? lifecycle.convergence !== "stable" : false)
  );
}

export function shouldPollAgentWorkspaceLifecycle(
  workspace?: Pick<AgentWorkspaceResponse, "lifecycle" | "workspace"> | null,
  options?: {
    configurationStatus?: RuntimeConfigurationStatus | null;
  },
): boolean {
  return (
    shouldPollRuntimeLifecycle(workspace?.lifecycle, options) ||
    workspace?.workspace.type === "CONNECTING" ||
    workspace?.workspace.type === "CONTROL_UNAVAILABLE"
  );
}
