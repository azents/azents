"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { trpc } from "@/trpc/client";
import {
  projectSubscriptionUsageState,
  supportsSubscriptionUsage,
} from "../subscriptionUsage";
import type {
  SubscriptionUsageSnapshot,
  SubscriptionUsageState,
} from "../subscriptionUsage";

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

interface SuccessfulSnapshotCache {
  handle: string;
  integrationId: string;
  snapshot: SubscriptionUsageSnapshot;
}

type SuccessfulSnapshotQueryKey = readonly [
  "subscriptionUsageLastSuccessful",
  string,
  string,
];

function successfulSnapshotQueryKey(
  handle: string,
  integrationId: string,
): SuccessfulSnapshotQueryKey {
  return ["subscriptionUsageLastSuccessful", handle, integrationId];
}

export function useSubscriptionUsageContainer(
  props: SubscriptionUsageContainerProps,
): SubscriptionUsageContainerOutput {
  const { enabled, handle, integrationId, provider } = props;
  const queryClient = useQueryClient();
  const snapshotQueryKey = useMemo(
    () => successfulSnapshotQueryKey(handle, integrationId),
    [handle, integrationId],
  );
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
  const successfulSnapshotCache = useRef<SuccessfulSnapshotCache | null>(null);

  useEffect(() => {
    if (query.data?.type === "available" || query.data?.type === "external") {
      successfulSnapshotCache.current = {
        handle,
        integrationId,
        snapshot: query.data,
      };
      queryClient.setQueryData<SubscriptionUsageSnapshot>(
        snapshotQueryKey,
        query.data,
      );
    }
  }, [handle, integrationId, query.data, queryClient, snapshotQueryKey]);

  const queryCachedSnapshot =
    queryClient.getQueryData<SubscriptionUsageSnapshot>(snapshotQueryKey) ??
    null;
  const lastSuccessfulSnapshot =
    successfulSnapshotCache.current?.handle === handle &&
    successfulSnapshotCache.current.integrationId === integrationId
      ? successfulSnapshotCache.current.snapshot
      : queryCachedSnapshot;
  const state = useMemo(
    (): SubscriptionUsageState =>
      projectSubscriptionUsageState(provider, enabled, {
        data: query.data ?? null,
        isError: query.isError,
        isFetching: query.isFetching,
        isLoading: query.isLoading,
        lastSuccessfulSnapshot,
      }),
    [
      enabled,
      lastSuccessfulSnapshot,
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
