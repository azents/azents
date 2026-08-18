"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceMemberDetailContainer } from "../containers/useWorkspaceMemberDetailContainer";
import { WorkspaceMemberDetailView } from "./WorkspaceMemberDetailView";
import type { WorkspaceMemberDetailContainerProps } from "../containers/useWorkspaceMemberDetailContainer";

/**
 * Workspace member detail container component
 *
 * Connects the container hook to the view.
 */
export const WorkspaceMemberDetail = createReactContainer<
  WorkspaceMemberDetailContainerProps,
  ReturnType<typeof useWorkspaceMemberDetailContainer>
>(
  "WorkspaceMemberDetail",
  useWorkspaceMemberDetailContainer,
  WorkspaceMemberDetailView,
);
