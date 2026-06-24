/** Agent feature state type */

import type { AgentAdminResponse, AgentResponse } from "@azents/public-client";

/** Agent list state */
export type AgentListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | {
      type: "READY";
      agents: AgentResponse[];
    };

/** Agent list role filter.
 * - "agent": regular agent (default). Also shown in sidebar
 * - "subagent": child agent called by another agent
 * - "all": all */
export type AgentRoleFilter = "agent" | "subagent" | "all";

/** Agent form state (Full Page) */
export type AgentFormState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "CREATE" }
  | { type: "EDIT"; agent: AgentResponse };

/** Mutation state */
export type MutationState =
  | {
      type: "IDLE";
      error: string | null;
      builtinToolErrors: Record<string, string[]> | null;
    }
  | { type: "SUBMITTING" };

/** Admin list state */
export type AdminListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; admins: AgentAdminResponse[] };
