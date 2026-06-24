"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceListContainer } from "../containers/useWorkspaceListContainer";
import { WorkspaceListView } from "./WorkspaceListView";
import type { WorkspaceListContainerProps } from "../containers/useWorkspaceListContainer";

/**
 * Workspace 목록 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const WorkspaceList = createReactContainer<
  WorkspaceListContainerProps,
  ReturnType<typeof useWorkspaceListContainer>
>("WorkspaceList", useWorkspaceListContainer, WorkspaceListView);
