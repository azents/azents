"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceDetailContainer } from "../containers/useWorkspaceDetailContainer";
import { WorkspaceDetailView } from "./WorkspaceDetailView";
import type { WorkspaceDetailContainerProps } from "../containers/useWorkspaceDetailContainer";

/**
 * Workspace detail container component
 *
 * Connects the container hook to the view.
 */
export const WorkspaceDetail = createReactContainer<
  WorkspaceDetailContainerProps,
  ReturnType<typeof useWorkspaceDetailContainer>
>("WorkspaceDetail", useWorkspaceDetailContainer, WorkspaceDetailView);
