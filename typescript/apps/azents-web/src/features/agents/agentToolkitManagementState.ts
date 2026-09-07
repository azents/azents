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
