/** Agent feature state type */

import type {
  AgentAdminResponse,
  AgentResponse,
  AgentToolkitManagementItemResponse,
  AgentToolkitResponse,
  HistoricalMemoryResponse,
  MemoryResponse,
  ToolkitConfigResponse,
} from "@azents/public-client";

/** Agent list state */
export type AgentListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      agents: AgentResponse[];
    };

/** Agent form state (Full Page) */
export type AgentFormState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "CREATE" }
  | { type: "EDIT"; agent: AgentResponse };

/** Mutation state */
export type MutationState =
  { type: "IDLE"; error: string | null } | { type: "SUBMITTING" };

/** Admin list state */
export type AdminListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; admins: AgentAdminResponse[] };

/** Memory settings selections and shared UI state. */
export type MemoryKindValue = "saved" | "historical";
export type SavedMemoryScopeValue = "agent" | "user";
export type HistoricalMemoryScopeValue = "team" | "user";

export interface MemoryDraft {
  type: string;
  name: string;
  description: string;
  content: string;
}

export type DraftState =
  | { type: "create"; draft: MemoryDraft }
  | { type: "edit"; memoryId: string; draft: MemoryDraft }
  | null;

export type SavedMemoryListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; memories: MemoryResponse[] };

export type ConsolidatedMemoryState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; markdown: string | null; publishedAt: string | null };

export type MemoryPaginationState =
  | { type: "IDLE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "END" };

export type HistoricalMemoryView = "overview" | "sessions";

export type HistoricalMemoryListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      memories: HistoricalMemoryResponse[];
      hasMore: boolean;
    };

export type AgentToolkitEditorState =
  | { type: "CLOSED" }
  | { type: "CATALOG"; tab: "new" | "workspace" }
  | { type: "CREATE"; toolkitType: string }
  | { type: "DETAIL"; toolkitConfigId: string }
  | { type: "EDIT"; toolkitConfigId: string };

export type AgentToolkitMutationState =
  { type: "IDLE" } | { type: "ERROR"; message: string };

export interface AgentToolkitSharedOption {
  value: string;
  label: string;
  toolkitType: string;
  description?: string | null;
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

export interface AgentToolkitSectionIdentity {
  handle: string;
  agentId: string;
}
export interface LegacyAgentToolkitSnapshot {
  agentToolkits: AgentToolkitResponse[];
  availableToolkits: ToolkitConfigResponse[];
  selectOptions: Array<{ value: string; label: string }>;
}
export type LegacyAgentToolkitState =
  | ({ type: "LOADING" } & LegacyAgentToolkitSnapshot)
  | ({ type: "ERROR" } & LegacyAgentToolkitSnapshot)
  | ({ type: "LOADING_ERROR" } & LegacyAgentToolkitSnapshot)
  | ({ type: "READY" } & LegacyAgentToolkitSnapshot);
export interface LegacyAgentToolkitSectionProps {
  state: LegacyAgentToolkitState;
  selectedToolkitId: string | null;
  onSelectionChange: (value: string | null) => void;
  onAttach: (toolkitId: string) => void;
  onDetach: (agentToolkitId: string) => void;
}
