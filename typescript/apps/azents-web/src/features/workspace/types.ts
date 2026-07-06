/**
 * Workspace feature ADT state
 */

import type { AgentResponse } from "@azents/public-client";

/** Invitation form error/success translation key (workspace.dashboard namespace) */
type InviteErrorKey =
  | "inviteError"
  | "inviteAlreadyMember"
  | "inviteAlreadyInvited";
type InviteSuccessKey = "inviteSuccess";

/** Invitation form state */
export type InviteFormState =
  | {
      type: "IDLE";
      error: InviteErrorKey | null;
      success: InviteSuccessKey | null;
    }
  | { type: "SENDING" };

/** Workspace member */
export interface WorkspaceMember {
  id: string;
  workspace_id: string;
  user_id: string;
  name: string;
  role: string;
  locale: string;
  created_at: string;
  updated_at: string;
}

/** Workspace invitation */
export interface WorkspaceInvitation {
  id: string;
  workspace_id: string;
  email: string;
  role: string;
  invited_by: string;
  status: string;
  created_at: string;
  updated_at: string;
}

/** Member list state */
export type MembersState =
  | { type: "LOADING" }
  | { type: "READY"; members: WorkspaceMember[] }
  | { type: "ERROR" };

/** Workspace invitation list state */
export type WorkspaceInvitationsState =
  | { type: "LOADING" }
  | { type: "READY"; invitations: WorkspaceInvitation[] }
  | { type: "ERROR" };

/** Workspace join request */
export interface WorkspaceJoinRequest {
  id: string;
  workspace_id: string;
  user_id: string;
  message: string | null;
  status: string;
  created_at: string;
}

/** Join request list state */
export type JoinRequestsState =
  | { type: "LOADING" }
  | { type: "READY"; joinRequests: WorkspaceJoinRequest[] }
  | { type: "ERROR" };

/** Member management notification translation key (workspace.dashboard namespace) */
type NotificationMessageKey =
  | "roleUpdateSuccess"
  | "roleUpdateError"
  | "removeSuccess"
  | "removeError"
  | "cancelSuccess"
  | "cancelError"
  | "cannotModifySelf"
  | "cannotModifyOwner"
  | "approveSuccess"
  | "approveError"
  | "rejectSuccess"
  | "rejectError"
  | "muteSuccess"
  | "muteError"
  | "deleteJoinRequestSuccess"
  | "deleteJoinRequestError";

/** Notification message state */
export interface NotificationState {
  type: "success" | "error";
  message: NotificationMessageKey;
}

/** Home agent tab filter. Persisted with URL `?view=`. */
export type AgentTeamFilter = "agents" | "all";

/** Agent for Home card display */
export interface EnrichedAgent extends AgentResponse {
  /** Last modified time (ISO) */
  lastActiveAt: string;
  /** Model display summary */
  modelSummary: string;
}

/** Home statistics card */
export interface WorkspaceHomeStats {
  /** Total primary agent count */
  totalAgents: number;
  /** enabled primary agent count */
  enabledAgents: number;
}

/** Home page state */
export type WorkspaceHomeState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | {
      type: "READY";
      /** workspace agents */
      agents: EnrichedAgent[];
      stats: WorkspaceHomeStats;
    };
