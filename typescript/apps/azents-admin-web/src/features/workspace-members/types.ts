/**
 * ADT definitions for the workspace members feature
 */

// --- API response types (re-exported from the generated client) ---
export type {
  WorkspaceUserResponse,
  WorkspaceUserRole,
} from "@azents/admin-client";

import type { WorkspaceUserResponse } from "@azents/admin-client";

// --- ADT state types ---

/** Workspace member list state */
export type WorkspaceMemberListState =
  | { type: "NO_WORKSPACE" }
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "LOADED";
      members: WorkspaceUserResponse[];
    };

/** Workspace member detail state */
export type WorkspaceMemberDetailState =
  | { type: "EMPTY" }
  | { type: "LOADING"; memberId: string }
  | { type: "ERROR"; memberId: string; message: string }
  | { type: "VIEWING"; member: WorkspaceUserResponse }
  | { type: "DELETING"; member: WorkspaceUserResponse };
