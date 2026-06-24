"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceDetailContainer } from "../containers/useWorkspaceDetailContainer";
import { WorkspaceDetailView } from "./WorkspaceDetailView";
import type { WorkspaceDetailContainerProps } from "../containers/useWorkspaceDetailContainer";

/**
 * Workspace 상세 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const WorkspaceDetail = createReactContainer<
  WorkspaceDetailContainerProps,
  ReturnType<typeof useWorkspaceDetailContainer>
>("WorkspaceDetail", useWorkspaceDetailContainer, WorkspaceDetailView);
