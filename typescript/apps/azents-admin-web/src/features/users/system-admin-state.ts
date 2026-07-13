interface SystemRoleAssignmentLike {
  user_id: string;
}

export interface SystemAdminRoleSummary {
  assigned: boolean;
  currentUser: boolean;
  finalAdmin: boolean;
}

export function getSystemAdminRoleSummary(
  assignments: readonly SystemRoleAssignmentLike[],
  currentAdminUserId: string | null,
  selectedUserId: string | null,
): SystemAdminRoleSummary {
  const assigned = assignments.some(
    (assignment) => assignment.user_id === selectedUserId,
  );
  return {
    assigned,
    currentUser: currentAdminUserId === selectedUserId,
    finalAdmin: assigned && assignments.length === 1,
  };
}
