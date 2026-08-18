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
 * Verification list container hook
 *
 * Fetches the verification list server-side through tRPC and converts it to an ADT.
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
