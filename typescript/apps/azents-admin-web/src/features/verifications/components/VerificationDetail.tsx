"use client";

import { createReactContainer } from "@/shared/lib/createReactContainer";
import { useVerificationDetailContainer } from "../containers/useVerificationDetailContainer";
import { VerificationDetailView } from "./VerificationDetailView";
import type { VerificationDetailContainerProps } from "../containers/useVerificationDetailContainer";

/**
 * Verification 상세 컨테이너 컴포넌트
 *
 * 컨테이너 훅과 뷰를 연결합니다.
 */
export const VerificationDetail = createReactContainer<
  VerificationDetailContainerProps,
  ReturnType<typeof useVerificationDetailContainer>
>("VerificationDetail", useVerificationDetailContainer, VerificationDetailView);
