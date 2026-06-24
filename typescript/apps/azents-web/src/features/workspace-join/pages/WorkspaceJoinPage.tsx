"use client";

/**
 * Workspace join request page
 *
 * Separates logic/UI with createReactContainer pattern.
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceJoinView } from "../components/WorkspaceJoinView";
import { useWorkspaceJoinContainer } from "../containers/useWorkspaceJoinContainer";

const WorkspaceJoinContainer = createReactContainer(
  "WorkspaceJoinContainer",
  useWorkspaceJoinContainer,
  WorkspaceJoinView,
);

interface WorkspaceJoinPageProps {
  handle: string;
}

export function WorkspaceJoinPage({
  handle,
}: WorkspaceJoinPageProps): React.ReactElement {
  return <WorkspaceJoinContainer handle={handle} />;
}
