"use client";

import { trpc } from "@/trpc/client";
import type {
  EmailVerificationResponse,
  VerificationListState,
} from "../types";

export interface VerificationListContainerProps {
  selectedVerificationId: string | null;
  onRowClick: (verification: EmailVerificationResponse) => void;
}

export interface VerificationListComponentProps {
  state: VerificationListState;
  selectedVerificationId: string | null;
  onRowClick: (verification: EmailVerificationResponse) => void;
}

/**
 * Verification 목록 컨테이너 훅
 *
 * tRPC를 사용하여 verification 목록을 서버사이드에서 가져오고 ADT로 변환합니다.
 */
export function useVerificationListContainer(
  props: VerificationListContainerProps,
): VerificationListComponentProps {
  const { data, isLoading, isError, error } = trpc.verification.list.useQuery();

  const state: VerificationListState = isLoading
    ? { type: "LOADING" }
    : isError
      ? {
          type: "ERROR",
          message: error.message,
        }
      : {
          type: "LOADED",
          verifications: data?.items ?? [],
        };

  return {
    state,
    selectedVerificationId: props.selectedVerificationId,
    onRowClick: props.onRowClick,
  };
}
