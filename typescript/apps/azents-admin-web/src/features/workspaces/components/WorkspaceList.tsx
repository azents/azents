"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceListContainer } from "../containers/useWorkspaceListContainer";
import { WorkspaceListView } from "./WorkspaceListView";
import type { WorkspaceListContainerProps } from "../containers/useWorkspaceListContainer";

/**
 * Workspace list container component
 *
 * Connects the container hook to the view.
 */
export const WorkspaceList = createReactContainer<
  WorkspaceListContainerProps,
  ReturnType<typeof useWorkspaceListContainer>
>("WorkspaceList", useWorkspaceListContainer, WorkspaceListView);
