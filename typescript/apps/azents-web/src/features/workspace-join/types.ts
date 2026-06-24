/**
 * Workspace join request page ADT state
 */

/** Non-member workspace page state */
export type WorkspaceJoinPageState =
  | { type: "LOADING" }
  | { type: "PENDING_INVITATION"; invitationId: string }
  | { type: "PENDING_REQUEST" }
  | { type: "IDLE" }
  | { type: "SUBMITTING" }
  | { type: "SUBMITTED" }
  | { type: "ERROR"; message: string };
