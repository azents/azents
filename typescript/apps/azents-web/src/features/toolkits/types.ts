/** Toolkit feature state type */

import type {
  ToolkitConfigResponse,
  ToolkitResponse,
  ToolkitScopeResponse,
} from "@azents/public-client";

/** Toolkit Config list state */
export type ToolkitConfigListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; configs: ToolkitConfigResponse[] };

/** Toolkit Config form state */
export type ToolkitConfigFormState =
  | { type: "LOADING" }
  | { type: "NOT_FOUND" }
  | { type: "CREATE" }
  | { type: "EDIT"; config: ToolkitConfigResponse };

/** Mutation state */
export type MutationState =
  | { type: "IDLE"; error: string | null }
  | { type: "SUBMITTING" };

/** Scope list state */
export type ScopeListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; scopes: ToolkitScopeResponse[] };

/** Toolkit (tool definition) list state */
export type ToolkitListState =
  | { type: "LOADING" }
  | { type: "ERROR" }
  | { type: "READY"; toolkits: ToolkitResponse[] };
