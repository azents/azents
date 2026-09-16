/**
 * ADT definitions for the workspace members feature
 */

// --- API response types (re-exported from the generated client) ---
export type {
  UserResponse,
  WorkspaceUserResponse,
  WorkspaceUserRole,
} from "@azents/admin-client";

import type {
  WorkspaceUserResponse,
  WorkspaceUserRole,
} from "@azents/admin-client";

export interface WorkspaceMemberFormData {
  userId: string;
  name: string;
  role: WorkspaceUserRole;
}

export interface SelectOption {
  value: string;
  label: string;
}

export type WorkspaceSelectorState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "READY"; options: SelectOption[] };

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
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "EDITING";
      member: WorkspaceUserResponse | null;
      isNew: boolean;
      ownerExists: boolean;
    }
  | {
      type: "SAVING";
      member: WorkspaceUserResponse | null;
      isNew: boolean;
      ownerExists: boolean;
    }
  | { type: "TRANSFERRING"; member: WorkspaceUserResponse }
  | { type: "DELETING"; member: WorkspaceUserResponse };
