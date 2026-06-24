/**
 * Workspaces feature ADT state
 */
import type { WorkspaceResponse } from "@azents/public-client";

/** Workspace list page state */
export type WorkspacesListState =
  | { type: "LOADING" }
  | { type: "READY"; workspaces: WorkspaceResponse[] }
  | { type: "ERROR"; error: string };

/** Workspace creation page state */
export type WorkspaceCreateState =
  | { type: "IDLE"; error: string | null }
  | { type: "CREATING" };

/** Received invitation item */
export interface ReceivedInvitation {
  id: string;
  workspace_id: string;
  workspace_name: string;
  workspace_handle: string;
  email: string;
  role: string;
  status: string;
  created_at: string;
}

/** Received invitation list state */
export type InvitationsState =
  | { type: "LOADING" }
  | { type: "READY"; invitations: ReceivedInvitation[] }
  | { type: "ERROR" };
