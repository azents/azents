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
