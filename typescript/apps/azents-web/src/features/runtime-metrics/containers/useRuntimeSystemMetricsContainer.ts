"use client";

import { useMemo } from "react";
import { trpc } from "@/trpc/client";
import type { RuntimeSystemMetricsOverviewState } from "../types";

const METRICS_REFETCH_INTERVAL_MS = 60_000;

export interface RuntimeSystemMetricsContainerInput {
  handle: string;
  agentId: string;
  enabled: boolean;
}

export interface RuntimeSystemMetricsContainerOutput {
  state: RuntimeSystemMetricsOverviewState;
}

function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "Runtime metrics request failed.";
}

export function useRuntimeSystemMetricsContainer({
  handle,
  agentId,
  enabled,
}: RuntimeSystemMetricsContainerInput): RuntimeSystemMetricsContainerOutput {
  const metricsQuery = trpc.chat.getAgentRuntimeSystemMetrics.useQuery(
    { handle, agentId },
    {
      enabled,
      refetchInterval: enabled ? METRICS_REFETCH_INTERVAL_MS : false,
      refetchOnReconnect: false,
      refetchOnWindowFocus: false,
    },
  );

  const state = useMemo<RuntimeSystemMetricsOverviewState>(() => {
    if (metricsQuery.isError) {
      return { type: "ERROR", message: errorMessage(metricsQuery.error) };
    }
    if (!metricsQuery.data) {
      return { type: "LOADING" };
    }
    return { type: "READY", metrics: metricsQuery.data };
  }, [metricsQuery.data, metricsQuery.error, metricsQuery.isError]);

  return { state };
}
