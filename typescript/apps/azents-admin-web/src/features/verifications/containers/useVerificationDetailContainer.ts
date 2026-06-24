"use client";

import { trpc } from "@/trpc/client";
import type { VerificationDetailState } from "../types";

export interface VerificationDetailContainerProps {
  verificationId: string | null;
}

export interface VerificationDetailComponentProps {
  state: VerificationDetailState;
}

/**
 * Verification 상세 컨테이너 훅
 *
 * tRPC를 사용하여 verification 상세를 서버사이드에서 가져오고 ADT로 변환합니다.
 * 읽기 전용 (생성/수정/삭제 없음).
 */
export function useVerificationDetailContainer(
  props: VerificationDetailContainerProps,
): VerificationDetailComponentProps {
  const { verificationId } = props;

  const { data, isLoading, isError, error } = trpc.verification.get.useQuery(
    { id: verificationId ?? "" },
    { enabled: verificationId !== null },
  );

  if (verificationId === null) {
    return { state: { type: "EMPTY" } };
  }

  const state: VerificationDetailState = isLoading
    ? { type: "LOADING", verificationId }
    : isError
      ? {
          type: "ERROR",
          verificationId,
          message: error.message,
        }
      : data
        ? {
            type: "LOADED",
            verification: data,
          }
        : { type: "LOADING", verificationId };

  return { state };
}
