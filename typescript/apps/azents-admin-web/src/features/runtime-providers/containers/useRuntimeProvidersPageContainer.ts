"use client";

import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type { RuntimeProviderResponse } from "@azents/admin-client";

export type RuntimeProviderItem = RuntimeProviderResponse;

export type RuntimeProviderListState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; items: RuntimeProviderItem[] };

export interface RuntimeProvidersPageContentProps {
  state: RuntimeProviderListState;
  selectedProviderId: string | null;
  selectedProvider: RuntimeProviderItem | null;
  updating: boolean;
  errorMessage: string | null;
  onSelectProvider: (providerId: string) => void;
  onToggleEnabled: (provider: RuntimeProviderItem) => void;
}

export function useRuntimeProvidersPageContainer(): RuntimeProvidersPageContentProps {
  const utils = trpc.useUtils();
  const providersQuery = trpc.runtimeProvider.list.useQuery();
  const [selectedProviderId, setSelectedProviderId] = useState<string | null>(
    null,
  );
  const updatePolicy = trpc.runtimeProvider.updatePolicy.useMutation({
    onSuccess: async () => {
      await utils.runtimeProvider.list.invalidate();
    },
  });

  const items = useMemo(
    () => providersQuery.data?.items ?? [],
    [providersQuery.data?.items],
  );
  const effectiveSelectedProviderId =
    selectedProviderId ?? items[0]?.provider_id ?? null;
  const selectedProvider =
    items.find((item) => item.provider_id === effectiveSelectedProviderId) ??
    null;
  const state: RuntimeProviderListState = providersQuery.isLoading
    ? { type: "LOADING" }
    : providersQuery.isError
      ? { type: "ERROR", message: providersQuery.error.message }
      : { type: "LOADED", items };

  const handleToggleEnabled = useCallback(
    (provider: RuntimeProviderItem): void => {
      updatePolicy.mutate({
        providerId: provider.provider_id,
        enabled: !provider.enabled,
        lifecycleState: provider.lifecycle_state,
        availabilityMode: provider.availability_mode,
      });
    },
    [updatePolicy],
  );

  return {
    state,
    selectedProviderId: effectiveSelectedProviderId,
    selectedProvider,
    updating: updatePolicy.isPending,
    errorMessage: updatePolicy.error?.message ?? null,
    onSelectProvider: setSelectedProviderId,
    onToggleEnabled: handleToggleEnabled,
  };
}
