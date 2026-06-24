"use client";

/**
 * Workspace member management page
 *
 * Separates logic/UI with createReactContainer pattern.
 * Composed with member invitation form.
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceMembersView } from "../components/WorkspaceMembersView";
import { useWorkspaceMembers } from "../containers/useWorkspaceMembers";

const WorkspaceMembersContainer = createReactContainer(
  "WorkspaceMembersContainer",
  useWorkspaceMembers,
  WorkspaceMembersView,
);

interface WorkspaceMembersProps {
  handle: string;
}

export function WorkspaceMembers({
  handle,
}: WorkspaceMembersProps): React.ReactElement {
  return <WorkspaceMembersContainer handle={handle} />;
}
