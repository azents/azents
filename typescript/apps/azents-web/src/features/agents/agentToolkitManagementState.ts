import type { AgentToolkitManagementItemResponse } from "@azents/public-client";

export type AgentToolkitEditorState =
  | { type: "CLOSED" }
  | { type: "SELECT_TYPE"; toolkitType: string | null }
  | { type: "CREATE"; toolkitType: string }
  | { type: "EDIT"; toolkitConfigId: string };

export type AgentToolkitMutationState =
  { type: "IDLE" } | { type: "ERROR"; message: string };

export interface AgentToolkitSharedOption {
  value: string;
  label: string;
  toolkitType: string;
}

export type AgentToolkitManagementState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      items: AgentToolkitManagementItemResponse[];
      toolkitTypes: Array<{ value: string; label: string }>;
      availableShared: AgentToolkitSharedOption[];
    };

export function canAuthorizeAgentToolkitOAuth(
  item: AgentToolkitManagementItemResponse,
  canAuthorizeShared: boolean,
): boolean {
  if (
    item.readiness !== "authorization_required" ||
    (item.ownership_scope === "workspace_shared" && !canAuthorizeShared)
  ) {
    return false;
  }
  return (
    item.toolkit.toolkit_type === "notion" ||
    item.toolkit.toolkit_type === "sentry" ||
    (item.toolkit.toolkit_type === "mcp" &&
      item.toolkit.config.auth_type === "oauth2")
  );
}

export function decodeAgentToolkitOAuthCallback(
  event: { origin: string; source: unknown; data: unknown },
  origin: string,
  popup: unknown,
): "SUCCESS" | "FAILURE" | null {
  if (
    popup == null ||
    event.origin !== origin ||
    event.source !== popup ||
    event.data == null ||
    typeof event.data !== "object" ||
    !("type" in event.data) ||
    event.data.type !== "azents-oauth-callback" ||
    !("success" in event.data) ||
    typeof event.data.success !== "boolean"
  ) {
    return null;
  }
  return event.data.success ? "SUCCESS" : "FAILURE";
}

export interface AgentToolkitManagementQuerySnapshot {
  loading: boolean;
  error: string | null;
  data?: {
    items: AgentToolkitManagementItemResponse[];
    available_shared: Array<{
      id: string;
      name: string;
      toolkit_type: string;
    }>;
  };
  toolkitDefinitions?: Array<{
    slug: string;
    name: string;
  }>;
}

export function projectAgentToolkitManagementState({
  loading,
  error,
  data,
  toolkitDefinitions,
}: AgentToolkitManagementQuerySnapshot): AgentToolkitManagementState {
  if (loading) {
    return { type: "LOADING" };
  }
  if (error != null) {
    return { type: "ERROR", message: error };
  }
  return {
    type: "READY",
    items: data?.items ?? [],
    toolkitTypes: (toolkitDefinitions ?? [])
      .filter((toolkit) => toolkit.slug !== "shell")
      .map((toolkit) => ({
        value: toolkit.slug,
        label: toolkit.name,
      })),
    availableShared: (data?.available_shared ?? []).map((toolkit) => ({
      value: toolkit.id,
      label: `${toolkit.name} (${toolkit.toolkit_type})`,
      toolkitType: toolkit.toolkit_type,
    })),
  };
}
