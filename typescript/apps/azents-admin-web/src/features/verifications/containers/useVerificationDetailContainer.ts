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
 * Verification detail container hook
 *
 * Fetches verification details server-side through tRPC and converts them to an ADT.
 * Read-only (no create, update, or delete operations).
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
