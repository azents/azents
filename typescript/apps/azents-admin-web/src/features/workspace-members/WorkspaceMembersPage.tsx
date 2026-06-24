"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspaceMembersPageContent } from "./components/WorkspaceMembersPageContent";
import { useWorkspaceMembersPageContainer } from "./containers/useWorkspaceMembersPageContainer";

/**
 * WorkspaceMembersPage 엔트리 포인트
 *
 * 컨테이너 패턴을 사용하여 상태 관리와 UI를 분리합니다.
 */
export const WorkspaceMembersPage = createReactContainer(
  "WorkspaceMembersPage",
  useWorkspaceMembersPageContainer,
  WorkspaceMembersPageContent,
);
