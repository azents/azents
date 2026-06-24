"use client";

/**
 * Workspace list page
 */
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspacesList } from "../components/WorkspacesList";
import { useWorkspacesList } from "../containers/useWorkspacesList";

export const WorkspacesListPage = createReactContainer(
  "WorkspacesListPage",
  useWorkspacesList,
  WorkspacesList,
);
