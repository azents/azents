"use client";

import { useCallback, useMemo } from "react";
import { trpc } from "@/trpc/client";
import type {
  SystemCatalogListState,
  SystemCatalogProvider,
  SystemCatalogStatus,
  SystemModelCatalogRefreshResponse,
} from "../types";

const SYSTEM_CATALOG_PROVIDERS: SystemCatalogProvider[] = [
  "openai",
  "xai",
  "xai_oauth",
  "anthropic",
  "google_gemini",
];

export interface ModelCatalogPageContentProps {
  state: SystemCatalogListState;
  catalogStatuses: SystemCatalogStatus[];
  allRefreshing: boolean;
  lastRefreshResult: SystemModelCatalogRefreshResponse | null;
  lastBulkRefreshResults: SystemModelCatalogRefreshResponse[] | null;
  refreshErrorMessage: string | null;
  onRefreshCatalog: (provider: SystemCatalogProvider) => void;
  onRefreshAllCatalogs: () => void;
}

export function useModelCatalogPageContainer(): ModelCatalogPageContentProps {
  const utils = trpc.useUtils();
  const catalogQuery = trpc.modelCatalog.listSystemCatalogs.useQuery();
  const refreshCatalog = trpc.modelCatalog.refreshSystemCatalog.useMutation({
    onSuccess: async () => {
      await utils.modelCatalog.listSystemCatalogs.invalidate();
    },
  });
  const refreshCatalogs = trpc.modelCatalog.refreshSystemCatalogs.useMutation({
    onSuccess: async () => {
      await utils.modelCatalog.listSystemCatalogs.invalidate();
    },
  });

  const catalogs = useMemo(
    () => catalogQuery.data?.items ?? [],
    [catalogQuery.data?.items],
  );
  const state: SystemCatalogListState = catalogQuery.isLoading
    ? { type: "LOADING" }
    : catalogQuery.isError
      ? { type: "ERROR", message: catalogQuery.error.message }
      : { type: "LOADED", catalogs };

  const catalogStatuses = useMemo<SystemCatalogStatus[]>(() => {
    return SYSTEM_CATALOG_PROVIDERS.map((provider) => {
      const catalog =
        catalogs.find((item) => item.provider === provider) ?? null;
      const refreshing =
        refreshCatalog.isPending &&
        refreshCatalog.variables.provider === provider;
      return { provider, catalog, refreshing };
    });
  }, [catalogs, refreshCatalog.isPending, refreshCatalog.variables]);

  const handleRefreshCatalog = useCallback(
    (provider: SystemCatalogProvider): void => {
      refreshCatalog.mutate({ provider });
    },
    [refreshCatalog],
  );

  const handleRefreshAllCatalogs = useCallback((): void => {
    refreshCatalogs.mutate();
  }, [refreshCatalogs]);

  return {
    state,
    catalogStatuses,
    allRefreshing: refreshCatalogs.isPending,
    lastRefreshResult: refreshCatalog.data ?? null,
    lastBulkRefreshResults: refreshCatalogs.data?.items ?? null,
    refreshErrorMessage:
      refreshCatalog.error?.message ?? refreshCatalogs.error?.message ?? null,
    onRefreshCatalog: handleRefreshCatalog,
    onRefreshAllCatalogs: handleRefreshAllCatalogs,
  };
}
