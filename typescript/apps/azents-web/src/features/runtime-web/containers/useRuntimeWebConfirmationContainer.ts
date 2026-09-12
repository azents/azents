"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { RuntimeWebConfirmationState } from "../types";

export interface RuntimeWebConfirmationContainerProps {
  endpointId: string;
}

export interface RuntimeWebConfirmationContainerOutput {
  state: RuntimeWebConfirmationState;
  onApprove: () => void;
  onReject: () => void;
  onCancel: () => void;
  onClose: () => void;
  onRetry: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Runtime Web request failed.";
}

export function useRuntimeWebConfirmationContainer({
  endpointId,
}: RuntimeWebConfirmationContainerProps): RuntimeWebConfirmationContainerOutput {
  const utils = trpc.useUtils();
  const input = { endpointId };
  const query = trpc.runtimeWeb.getByEndpointId.useQuery(input, {
    refetchInterval: 5_000,
  });
  const invalidate = async (): Promise<void> => {
    await utils.runtimeWeb.getByEndpointId.invalidate(input);
  };
  const approve = trpc.runtimeWeb.approveByEndpointId.useMutation({
    onSuccess: invalidate,
  });
  const reject = trpc.runtimeWeb.rejectByEndpointId.useMutation({
    onSuccess: invalidate,
  });
  const cancel = trpc.runtimeWeb.cancelByEndpointId.useMutation({
    onSuccess: invalidate,
  });
  const close = trpc.runtimeWeb.closeByEndpointId.useMutation({
    onSuccess: invalidate,
  });

  const state = useMemo<RuntimeWebConfirmationState>(() => {
    if (query.isLoading) {
      return { type: "LOADING" };
    }
    if (query.isError || query.data == null) {
      return {
        type: "ERROR",
        message: errorMessage(query.error),
      };
    }
    const action = approve.isPending
      ? "approve"
      : reject.isPending
        ? "reject"
        : cancel.isPending
          ? "cancel"
          : close.isPending
            ? "close"
            : null;
    const mutationError =
      approve.error ?? reject.error ?? cancel.error ?? close.error;
    return {
      type: "READY",
      service: query.data,
      action,
      actionError: mutationError === null ? null : errorMessage(mutationError),
    };
  }, [
    approve.error,
    approve.isPending,
    cancel.error,
    cancel.isPending,
    close.error,
    close.isPending,
    query.data,
    query.error,
    query.isError,
    query.isLoading,
    reject.error,
    reject.isPending,
  ]);

  const onApprove = useCallback((): void => {
    const service = query.data;
    const request = service?.current_request;
    if (service == null || request?.state !== "pending") {
      return;
    }
    approve.mutate({
      endpointId,
      requestId: request.id,
      expectedRevision: request.revision,
      durationSeconds: service.duration_seconds,
      durationRevision: service.duration_configuration_revision,
    });
  }, [approve, endpointId, query.data]);

  const onReject = useCallback((): void => {
    const request = query.data?.current_request;
    if (request?.state !== "pending") {
      return;
    }
    reject.mutate({
      endpointId,
      requestId: request.id,
      expectedRevision: request.revision,
    });
  }, [endpointId, query.data?.current_request, reject]);

  const onCancel = useCallback((): void => {
    const request = query.data?.current_request;
    if (request?.state !== "pending") {
      return;
    }
    cancel.mutate({
      endpointId,
      requestId: request.id,
      expectedRevision: request.revision,
    });
  }, [cancel, endpointId, query.data?.current_request]);

  const onClose = useCallback((): void => {
    const service = query.data;
    const cycle = service?.current_cycle;
    if (service == null || cycle == null || !service.active) {
      return;
    }
    close.mutate({
      endpointId,
      cycleId: cycle.id,
      expectedEndpointRevision: service.endpoint.authority_revision,
    });
  }, [close, endpointId, query.data]);

  return {
    state,
    onApprove,
    onReject,
    onCancel,
    onClose,
    onRetry: () => {
      void utils.runtimeWeb.getByEndpointId.invalidate(input);
    },
  };
}
