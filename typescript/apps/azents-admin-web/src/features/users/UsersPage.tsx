"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { UsersPageContent } from "./components/UsersPageContent";
import { useUsersPageContainer } from "./containers/useUsersPageContainer";

/**
 * UsersPage 엔트리 포인트
 *
 * 컨테이너 패턴을 사용하여 상태 관리와 UI를 분리합니다.
 */
export const UsersPage = createReactContainer(
  "UsersPage",
  useUsersPageContainer,
  UsersPageContent,
);
