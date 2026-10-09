"use client";

import { useHash } from "@mantine/hooks";
import { useCallback, useMemo } from "react";
import {
  runtimeWebReturnDestination,
  runtimeWebReturnTargetWithFragment,
} from "@/shared/lib/runtime-web-return-target";
import { trpc } from "@/trpc/client";
import { useRuntimeWebActivationDuration } from "./useRuntimeWebActivationDuration";
import type {
  RuntimeWebActivationState,
  RuntimeWebDurationSeconds,
} from "../types";

export interface RuntimeWebActivationContainerProps {
  serviceId: string;
  returnTarget: string;
}

export interface RuntimeWebActivationContainerOutput {
  state: RuntimeWebActivationState;
  applicationUrl: string | null;
  duration: RuntimeWebDurationSeconds;
  onDurationChange: (duration: RuntimeWebDurationSeconds) => void;
  onTurnOn: (duration: RuntimeWebDurationSeconds) => void;
  onRetry: () => void;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Runtime Web request failed.";
}

export function useRuntimeWebActivationContainer({
  serviceId,
  returnTarget,
}: RuntimeWebActivationContainerProps): RuntimeWebActivationContainerOutput {
  const [fragment] = useHash();
  const utils = trpc.useUtils();
  const input = useMemo(() => ({ serviceId }), [serviceId]);
  const query = trpc.runtimeWeb.getById.useQuery(input, {
    refetchInterval: 5_000,
    refetchOnWindowFocus: true,
  });
  const invalidate = useCallback(async (): Promise<void> => {
    await utils.runtimeWeb.getById.invalidate(input);
  }, [input, utils.runtimeWeb.getById]);
  const turnOn = trpc.runtimeWeb.turnOnById.useMutation({
    onSuccess: (service) => {
      if (service.url === null) {
        void invalidate();
        return;
      }
      window.location.assign(
        runtimeWebReturnDestination(
          service.url,
          runtimeWebReturnTargetWithFragment(
            returnTarget,
            window.location.hash,
          ),
        ),
      );
    },
  });

  const state = useMemo<RuntimeWebActivationState>(() => {
    if (query.isLoading) {
      return { type: "LOADING" };
    }
    if (query.isError || query.data == null) {
      return { type: "ERROR", message: errorMessage(query.error) };
    }
    return {
      type: "READY",
      service: query.data,
      action: turnOn.isPending ? "turnOn" : null,
      actionError: turnOn.error === null ? null : errorMessage(turnOn.error),
    };
  }, [
    query.data,
    query.error,
    query.isError,
    query.isLoading,
    turnOn.error,
    turnOn.isPending,
  ]);

  const durationProps = useRuntimeWebActivationDuration(state);

  const onTurnOn = useCallback(
    (duration: RuntimeWebDurationSeconds): void => {
      const service = query.data;
      if (service == null || service.on) {
        return;
      }
      turnOn.mutate({
        serviceId,
        expectedRevision: service.revision,
        selectedDurationSeconds: duration,
        operationKey: crypto.randomUUID(),
      });
    },
    [query.data, serviceId, turnOn],
  );

  return {
    state,
    ...durationProps,
    applicationUrl: query.data?.url
      ? runtimeWebReturnDestination(
          query.data.url,
          runtimeWebReturnTargetWithFragment(returnTarget, fragment),
        )
      : null,
    onTurnOn,
    onRetry: () => {
      void utils.runtimeWeb.getById.invalidate(input);
    },
  };
}
