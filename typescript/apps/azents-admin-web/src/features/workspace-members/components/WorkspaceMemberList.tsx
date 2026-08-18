"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceMemberListContainer } from "../containers/useWorkspaceMemberListContainer";
import { WorkspaceMemberListView } from "./WorkspaceMemberListView";
import type { WorkspaceMemberListContainerProps } from "../containers/useWorkspaceMemberListContainer";

/**
 * Workspace member list container component
 *
 * Connects the container hook to the view.
 */
export const WorkspaceMemberList = createReactContainer<
  WorkspaceMemberListContainerProps,
  ReturnType<typeof useWorkspaceMemberListContainer>
>(
  "WorkspaceMemberList",
  useWorkspaceMemberListContainer,
  WorkspaceMemberListView,
);
