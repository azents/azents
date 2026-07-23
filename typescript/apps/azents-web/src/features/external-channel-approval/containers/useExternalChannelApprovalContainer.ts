"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type {
  ExternalChannelApprovalActionError,
  ExternalChannelApprovalDecision,
  ExternalChannelApprovalState,
} from "../types";

export interface ExternalChannelApprovalContainerProps {
  accessRequestId: string;
}

export interface ExternalChannelApprovalContainerOutput {
  state: ExternalChannelApprovalState;
  onDecision: (decision: ExternalChannelApprovalDecision) => void;
  onRetry: () => void;
}

function errorCode(error: unknown): string | null {
  if (
    typeof error !== "object" ||
    error === null ||
    !("data" in error) ||
    typeof error.data !== "object" ||
    error.data === null ||
    !("code" in error.data) ||
    typeof error.data.code !== "string"
  ) {
    return null;
  }
  return error.data.code;
}

export function useExternalChannelApprovalContainer({
  accessRequestId,
}: ExternalChannelApprovalContainerProps): ExternalChannelApprovalContainerOutput {
  const utils = trpc.useUtils();
  const query = trpc.externalChannel.getApprovalRequest.useQuery(
    { accessRequestId },
    { retry: false },
  );
  const mutation = trpc.externalChannel.decideApprovalRequest.useMutation({
    onSettled: (): void => {
      void utils.externalChannel.getApprovalRequest.invalidate({
        accessRequestId,
      });
    },
  });

  const state = useMemo<ExternalChannelApprovalState>(() => {
    if (query.isLoading) {
      return { type: "LOADING" };
    }
    if (query.isError) {
      const code = errorCode(query.error);
      if (code === "UNAUTHORIZED") {
        return { type: "UNAUTHORIZED" };
      }
      if (code === "NOT_FOUND") {
        return { type: "NOT_FOUND" };
      }
      return { type: "ERROR" };
    }
    const request = mutation.data ?? query.data;
    if (request == null) {
      return { type: "NOT_FOUND" };
    }
    const mutationCode = mutation.isError ? errorCode(mutation.error) : null;
    const actionError: ExternalChannelApprovalActionError | null =
      request.status !== "pending"
        ? null
        : mutationCode === "CONFLICT"
          ? "CONFLICT"
          : mutation.isError
            ? "ERROR"
            : null;
    return {
      type: "READY",
      request,
      submittingDecision: mutation.isPending
        ? mutation.variables.decision
        : null,
      actionError,
    };
  }, [
    mutation.data,
    mutation.error,
    mutation.isError,
    mutation.isPending,
    mutation.variables?.decision,
    query.data,
    query.error,
    query.isError,
    query.isLoading,
  ]);

  const onDecision = useCallback(
    (decision: ExternalChannelApprovalDecision): void => {
      mutation.mutate({ accessRequestId, decision });
    },
    [accessRequestId, mutation],
  );
  const onRetry = useCallback((): void => {
    mutation.reset();
    void query.refetch();
  }, [mutation, query]);

  return { state, onDecision, onRetry };
}
