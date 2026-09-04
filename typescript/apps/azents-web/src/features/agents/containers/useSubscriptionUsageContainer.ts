"use client";

import { useCallback } from "react";
import { supportsSubscriptionUsage } from "@/shared/subscription-usage/subscriptionUsage";
import { useSubscriptionUsageProjection } from "@/shared/subscription-usage/useSubscriptionUsageProjection";
import { trpc } from "@/trpc/client";
import type { SubscriptionUsageProjectionOutput } from "@/shared/subscription-usage/useSubscriptionUsageProjection";

export interface SubscriptionUsageContainerProps {
  enabled: boolean;
  handle: string;
  integrationId: string;
  provider: string;
}

export type SubscriptionUsageContainerOutput =
  SubscriptionUsageProjectionOutput;

export function useSubscriptionUsageContainer(
  props: SubscriptionUsageContainerProps,
): SubscriptionUsageContainerOutput {
  const { enabled, handle, integrationId, provider } = props;
  const query = trpc.llmProviderIntegration.subscriptionUsage.useQuery(
    { handle, integrationId },
    {
      enabled: enabled && supportsSubscriptionUsage(provider),
      refetchOnWindowFocus: true,
      retry: false,
      staleTime: 60_000,
    },
  );
  const { refetch } = query;
  const onRefresh = useCallback(async (): Promise<void> => {
    await refetch();
  }, [refetch]);

  return useSubscriptionUsageProjection({
    data: query.data ?? null,
    enabled,
    handle,
    integrationId,
    isError: query.isError,
    isFetching: query.isFetching,
    isLoading: query.isLoading,
    onRefresh,
    provider,
  });
}
