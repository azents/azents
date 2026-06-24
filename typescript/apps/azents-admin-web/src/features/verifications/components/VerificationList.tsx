"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useVerificationListContainer } from "../containers/useVerificationListContainer";
import { VerificationListView } from "./VerificationListView";
import type { VerificationListContainerProps } from "../containers/useVerificationListContainer";

/**
 * Verification 목록 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const VerificationList = createReactContainer<
  VerificationListContainerProps,
  ReturnType<typeof useVerificationListContainer>
>("VerificationList", useVerificationListContainer, VerificationListView);
