export type WorkspaceMemberRole = "owner" | "manager" | "member";

interface AvailableRoleInput {
  createMode: boolean;
  ownerExists: boolean;
  currentRole: WorkspaceMemberRole | null;
}

/** Return roles that may be selected without bypassing ownership transfer. */
export function getAvailableWorkspaceMemberRoles({
  createMode,
  ownerExists,
  currentRole,
}: AvailableRoleInput): WorkspaceMemberRole[] {
  if (createMode && !ownerExists) {
    return ["owner", "manager", "member"];
  }
  if (currentRole === "owner") {
    return ["owner"];
  }
  return ["manager", "member"];
}

/** Choose the safest useful role for a new membership form. */
export function getDefaultWorkspaceMemberRole(
  ownerExists: boolean,
): WorkspaceMemberRole {
  return ownerExists ? "member" : "owner";
}

/** Owner mutation must use ownership transfer rather than direct role/delete actions. */
export function canDirectlyMutateWorkspaceMember(
  role: WorkspaceMemberRole,
): boolean {
  return role !== "owner";
}

export interface WorkspaceMemberMutationLocation {
  workspace: string;
  memberId: string | null;
  mode: "view";
}

/** Fence a completed mutation to the Workspace where it started. */
export function getWorkspaceMemberMutationLocation(
  workspaceHandle: string,
  memberId: string | null,
): WorkspaceMemberMutationLocation {
  return {
    workspace: workspaceHandle,
    memberId,
    mode: "view",
  };
}
