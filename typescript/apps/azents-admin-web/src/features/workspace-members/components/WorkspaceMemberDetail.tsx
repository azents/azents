"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useWorkspaceMemberDetailContainer } from "../containers/useWorkspaceMemberDetailContainer";
import { WorkspaceMemberDetailView } from "./WorkspaceMemberDetailView";
import type { WorkspaceMemberDetailContainerProps } from "../containers/useWorkspaceMemberDetailContainer";

/**
 * WorkspaceMember 상세 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const WorkspaceMemberDetail = createReactContainer<
  WorkspaceMemberDetailContainerProps,
  ReturnType<typeof useWorkspaceMemberDetailContainer>
>(
  "WorkspaceMemberDetail",
  useWorkspaceMemberDetailContainer,
  WorkspaceMemberDetailView,
);
