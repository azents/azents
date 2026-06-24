"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceMemberListContainer } from "../containers/useWorkspaceMemberListContainer";
import { WorkspaceMemberListView } from "./WorkspaceMemberListView";
import type { WorkspaceMemberListContainerProps } from "../containers/useWorkspaceMemberListContainer";

/**
 * WorkspaceMember 목록 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const WorkspaceMemberList = createReactContainer<
  WorkspaceMemberListContainerProps,
  ReturnType<typeof useWorkspaceMemberListContainer>
>(
  "WorkspaceMemberList",
  useWorkspaceMemberListContainer,
  WorkspaceMemberListView,
);
