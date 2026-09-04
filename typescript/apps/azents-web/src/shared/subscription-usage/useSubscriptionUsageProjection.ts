"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";
import { projectSubscriptionUsageState } from "./subscriptionUsage";
import type {
  SubscriptionUsageResponse,
  SubscriptionUsageSnapshot,
  SubscriptionUsageState,
} from "./subscriptionUsage";

export interface SubscriptionUsageProjectionProps {
  data: SubscriptionUsageResponse | null;
  enabled: boolean;
  handle: string;
  integrationId: string;
  isError: boolean;
  isFetching: boolean;
  isLoading: boolean;
  onRefresh: () => Promise<void>;
  provider: string;
}

export interface SubscriptionUsageProjectionOutput {
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

export function useSubscriptionUsageProjection(
  props: SubscriptionUsageProjectionProps,
): SubscriptionUsageProjectionOutput {
  const {
    data,
    enabled,
    handle,
    integrationId,
    isError,
    isFetching,
    isLoading,
    onRefresh,
    provider,
  } = props;
  const queryClient = useQueryClient();
  const snapshotQueryKey = useMemo(
    () => successfulSnapshotQueryKey(handle, integrationId),
    [handle, integrationId],
  );
  const successfulSnapshotCache = useRef<SuccessfulSnapshotCache | null>(null);

  useEffect(() => {
    if (data?.type === "unavailable" && data.reason === "no_credit_limit") {
      successfulSnapshotCache.current = null;
      queryClient.removeQueries({ exact: true, queryKey: snapshotQueryKey });
      return;
    }
    if (data?.type === "available" || data?.type === "external") {
      successfulSnapshotCache.current = {
        handle,
        integrationId,
        snapshot: data,
      };
      queryClient.setQueryData<SubscriptionUsageSnapshot>(
        snapshotQueryKey,
        data,
      );
    }
  }, [data, handle, integrationId, queryClient, snapshotQueryKey]);

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
        data,
        isError,
        isFetching,
        isLoading,
        lastSuccessfulSnapshot,
      }),
    [
      data,
      enabled,
      isError,
      isFetching,
      isLoading,
      lastSuccessfulSnapshot,
      provider,
    ],
  );

  return { state, onRefresh };
}
