"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type {
  RuntimeWebDurationSeconds,
  RuntimeWebMutationAction,
  RuntimeWebServicesState,
} from "../types";
import type { RuntimeWebServiceResponse } from "@azents/public-client";

export interface RuntimeWebServicesContainerProps {
  handle: string;
  agentId: string;
  enabled: boolean;
  autoRefreshVisible: boolean;
  runtimeAvailable: boolean;
}

export interface RuntimeWebCreateInput {
  port: number;
  label: string | null;
  selectedDurationSeconds: RuntimeWebDurationSeconds;
  turnOn: boolean;
}

export interface RuntimeWebUpdateInput {
  label?: string | null;
  selectedDurationSeconds?: RuntimeWebDurationSeconds;
}

export interface RuntimeWebServicesContainerOutput {
  state: RuntimeWebServicesState;
  action: RuntimeWebMutationAction;
  mutationError: string | null;
  onCreate: (input: RuntimeWebCreateInput) => void;
  onUpdate: (
    service: RuntimeWebServiceResponse,
    input: RuntimeWebUpdateInput,
  ) => void;
  onTurnOn: (
    service: RuntimeWebServiceResponse,
    duration: RuntimeWebDurationSeconds,
  ) => void;
  onTurnOff: (service: RuntimeWebServiceResponse) => void;
  onReset: (service: RuntimeWebServiceResponse) => void;
  onDelete: (service: RuntimeWebServiceResponse) => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Runtime Web request failed.";
}

function operationKey(): string {
  return crypto.randomUUID();
}

export function useRuntimeWebServicesContainer({
  handle,
  agentId,
  enabled,
  autoRefreshVisible,
  runtimeAvailable,
}: RuntimeWebServicesContainerProps): RuntimeWebServicesContainerOutput {
  const utils = trpc.useUtils();
  const input = useMemo(() => ({ handle, agentId }), [agentId, handle]);
  const query = trpc.runtimeWeb.list.useQuery(input, {
    enabled,
    refetchInterval: enabled && autoRefreshVisible ? 5_000 : false,
    refetchOnWindowFocus: enabled,
  });
  const invalidate = useCallback(async (): Promise<void> => {
    await Promise.all([
      utils.runtimeWeb.list.invalidate(input),
      utils.runtimeWeb.get.invalidate(),
      utils.runtimeWeb.getById.invalidate(),
    ]);
  }, [
    input,
    utils.runtimeWeb.get,
    utils.runtimeWeb.getById,
    utils.runtimeWeb.list,
  ]);
  const create = trpc.runtimeWeb.create.useMutation({ onSuccess: invalidate });
  const update = trpc.runtimeWeb.update.useMutation({ onSuccess: invalidate });
  const turnOn = trpc.runtimeWeb.turnOn.useMutation({ onSuccess: invalidate });
  const turnOff = trpc.runtimeWeb.turnOff.useMutation({
    onSuccess: invalidate,
  });
  const reset = trpc.runtimeWeb.reset.useMutation({ onSuccess: invalidate });
  const remove = trpc.runtimeWeb.delete.useMutation({ onSuccess: invalidate });

  const state = useMemo<RuntimeWebServicesState>(() => {
    if (!enabled) {
      return { type: "READY", services: [], runtimeAvailable: false };
    }
    if (query.isLoading) {
      return { type: "LOADING" };
    }
    if (query.isError || query.data == null) {
      return { type: "ERROR", message: errorMessage(query.error) };
    }
    return {
      type: "READY",
      services: query.data.items,
      runtimeAvailable,
    };
  }, [
    enabled,
    query.data,
    query.error,
    query.isError,
    query.isLoading,
    runtimeAvailable,
  ]);

  const action: RuntimeWebMutationAction = create.isPending
    ? "create"
    : update.isPending
      ? "update"
      : turnOn.isPending
        ? "turnOn"
        : turnOff.isPending
          ? "turnOff"
          : reset.isPending
            ? "reset"
            : remove.isPending
              ? "delete"
              : null;
  const mutationError =
    create.error ??
    update.error ??
    turnOn.error ??
    turnOff.error ??
    reset.error ??
    remove.error;

  const onCreate = useCallback(
    (createInput: RuntimeWebCreateInput): void => {
      create.mutate({ ...input, ...createInput, operationKey: operationKey() });
    },
    [create, input],
  );
  const onUpdate = useCallback(
    (
      service: RuntimeWebServiceResponse,
      updateInput: RuntimeWebUpdateInput,
    ): void => {
      update.mutate({
        ...input,
        serviceId: service.id,
        expectedRevision: service.revision,
        operationKey: operationKey(),
        ...updateInput,
      });
    },
    [input, update],
  );
  const onTurnOn = useCallback(
    (
      service: RuntimeWebServiceResponse,
      duration: RuntimeWebDurationSeconds,
    ): void => {
      turnOn.mutate({
        ...input,
        serviceId: service.id,
        expectedRevision: service.revision,
        selectedDurationSeconds: duration,
        operationKey: operationKey(),
      });
    },
    [input, turnOn],
  );
  const onTurnOff = useCallback(
    (service: RuntimeWebServiceResponse): void => {
      turnOff.mutate({
        ...input,
        serviceId: service.id,
        expectedRevision: service.revision,
        operationKey: operationKey(),
      });
    },
    [input, turnOff],
  );
  const onReset = useCallback(
    (service: RuntimeWebServiceResponse): void => {
      reset.mutate({
        ...input,
        serviceId: service.id,
        expectedRevision: service.revision,
        operationKey: operationKey(),
      });
    },
    [input, reset],
  );
  const onDelete = useCallback(
    (service: RuntimeWebServiceResponse): void => {
      remove.mutate({
        ...input,
        serviceId: service.id,
        expectedRevision: service.revision,
        operationKey: operationKey(),
      });
    },
    [input, remove],
  );

  return {
    state,
    action,
    mutationError: mutationError === null ? null : errorMessage(mutationError),
    onCreate,
    onUpdate,
    onTurnOn,
    onTurnOff,
    onReset,
    onDelete,
  };
}
