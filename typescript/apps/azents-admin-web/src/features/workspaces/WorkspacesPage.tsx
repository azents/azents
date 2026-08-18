"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspacesPageContent } from "./components/WorkspacesPageContent";
import { useWorkspacesPageContainer } from "./containers/useWorkspacesPageContainer";

/**
 * Entry point for WorkspacesPage
 *
 * Uses the container pattern to separate state management from UI.
 */
export const WorkspacesPage = createReactContainer(
  "WorkspacesPage",
  useWorkspacesPageContainer,
  WorkspacesPageContent,
);
