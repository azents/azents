"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceMembersPageContent } from "./components/WorkspaceMembersPageContent";
import { useWorkspaceMembersPageContainer } from "./containers/useWorkspaceMembersPageContainer";

/**
 * Entry point for WorkspaceMembersPage
 *
 * Uses the container pattern to separate state management from UI.
 */
export const WorkspaceMembersPage = createReactContainer(
  "WorkspaceMembersPage",
  useWorkspaceMembersPageContainer,
  WorkspaceMembersPageContent,
);
