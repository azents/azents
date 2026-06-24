"use client";

/**
 * Workspace Home page entry — "Our team agents" view.
 */

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceHome } from "../components/WorkspaceHome";
import { useWorkspaceHomeContainer } from "../containers/useWorkspaceHomeContainer";

const WorkspaceHomePageContainer = createReactContainer(
  "WorkspaceHomePageContainer",
  useWorkspaceHomeContainer,
  WorkspaceHome,
);

interface WorkspaceHomePageProps {
  handle: string;
}

export function WorkspaceHomePage({
  handle,
}: WorkspaceHomePageProps): React.ReactElement {
  return <WorkspaceHomePageContainer handle={handle} />;
}
