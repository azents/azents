"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { WorkspacesPageContent } from "./components/WorkspacesPageContent";
import { useWorkspacesPageContainer } from "./containers/useWorkspacesPageContainer";

/**
 * WorkspacesPage 엔트리 포인트
 *
 * 컨테이너 패턴을 사용하여 상태 관리와 UI를 분리합니다.
 */
export const WorkspacesPage = createReactContainer(
  "WorkspacesPage",
  useWorkspacesPageContainer,
  WorkspacesPageContent,
);
