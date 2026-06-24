"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { VerificationsPageContent } from "./components/VerificationsPageContent";
import { useVerificationsPageContainer } from "./containers/useVerificationsPageContainer";

/**
 * VerificationsPage 엔트리 포인트
 *
 * 컨테이너 패턴을 사용하여 상태 관리와 UI를 분리합니다.
 */
export const VerificationsPage = createReactContainer(
  "VerificationsPage",
  useVerificationsPageContainer,
  VerificationsPageContent,
);
