"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import {
  projectSubscriptionUsageState,
  supportsSubscriptionUsage,
} from "../subscriptionUsage";
import type { SubscriptionUsageState } from "../subscriptionUsage";

export interface SubscriptionUsageContainerProps {
  enabled: boolean;
  handle: string;
  integrationId: string;
  provider: string;
}

export interface SubscriptionUsageContainerOutput {
  state: SubscriptionUsageState;
  onRefresh: () => Promise<void>;
}

export function useSubscriptionUsageContainer(
  props: SubscriptionUsageContainerProps,
): SubscriptionUsageContainerOutput {
  const { enabled, handle, integrationId, provider } = props;
  const queryEnabled = enabled && supportsSubscriptionUsage(provider);
  const query = trpc.llmProviderIntegration.subscriptionUsage.useQuery(
    { handle, integrationId },
    {
      enabled: queryEnabled,
      refetchOnWindowFocus: true,
      retry: false,
      staleTime: 60_000,
    },
  );

  const state = useMemo(
    (): SubscriptionUsageState =>
      projectSubscriptionUsageState(provider, enabled, {
        data: query.data ?? null,
        isError: query.isError,
        isFetching: query.isFetching,
        isLoading: query.isLoading,
      }),
    [
      enabled,
      provider,
      query.data,
      query.isError,
      query.isFetching,
      query.isLoading,
    ],
  );

  const { refetch } = query;
  const onRefresh = useCallback(async (): Promise<void> => {
    await refetch();
  }, [refetch]);

  return { state, onRefresh };
}
