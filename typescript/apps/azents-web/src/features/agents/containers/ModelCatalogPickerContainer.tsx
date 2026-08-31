"use client";

import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import {
  ModelCatalogPicker,
  type ModelCatalogPickerState,
  type PickerCatalogUiState,
} from "../components/ModelCatalogPicker";
import type {
  ModelCatalogAttemptState,
  ModelCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "../model-selection";

const PAGE_SIZE = 50;

interface LoadedCatalogPage {
  models: SelectableModelCandidate[];
  catalog: ModelCatalogState;
}

export interface ModelCatalogPickerContainerProps {
  opened: boolean;
  title: string;
  handle: string;
  integrations: ProviderIntegrationOption[];
  selectedIntegrationId: string | null;
  selectedValue: string | null;
  onClose: () => void;
  onSelectIntegration: (integrationId: string) => void;
  onSelectModel: (model: SelectableModelCandidate) => void;
  onSyncCatalog: (integrationId: string) => Promise<void>;
}

function catalogUiState(params: {
  selectedIntegrationId: string | null;
  queryLoading: boolean;
  queryFetching: boolean;
  catalogState: ModelCatalogState | null;
  models: SelectableModelCandidate[];
  hasNextPage: boolean;
}): PickerCatalogUiState {
  const {
    selectedIntegrationId,
    queryLoading,
    queryFetching,
    catalogState,
    models,
    hasNextPage,
  } = params;
  if (selectedIntegrationId == null) {
    return { type: "NO_INTEGRATION" };
  }
  if (queryLoading && catalogState == null) {
    return { type: "LOADING_STATUS" };
  }
  const latestAttempt = catalogState?.latestAttempt ?? null;
  if (latestAttempt?.status === "failed") {
    if (catalogState?.currentSnapshotId == null) {
      return { type: "FAILED_WITHOUT_SNAPSHOT", attempt: latestAttempt };
    }
    return { type: "READY_WITH_FAILED_ATTEMPT", attempt: latestAttempt };
  }
  if (
    latestAttempt?.status === "running" &&
    catalogState?.currentSnapshotId == null
  ) {
    return { type: "SYNCING_WITHOUT_SNAPSHOT" };
  }
  if (catalogState != null && catalogState.currentSnapshotId == null) {
    return { type: "NEVER_SYNCED" };
  }
  if (queryFetching && hasNextPage) {
    return { type: "LOADING_NEXT_PAGE" };
  }
  if (!queryLoading && models.length === 0) {
    return { type: "READY_EMPTY" };
  }
  return { type: "READY" };
}

function syncSupportedForIntegration(
  integration: ProviderIntegrationOption | null,
): boolean {
  if (integration == null) {
    return false;
  }
  return (
    integration.provider === "aws_bedrock" ||
    integration.provider === "chatgpt_oauth" ||
    integration.provider === "kimi_oauth" ||
    integration.provider === "google_vertex_ai" ||
    integration.provider === "openrouter"
  );
}

function catalogStateFromPage(data: {
  models: SelectableModelCandidate[];
  catalog: {
    catalog_id: string;
    catalog_scope: "system" | "integration";
    current_snapshot_id: string | null;
    current_snapshot_created_at: string | null;
    latest_attempt: ModelCatalogAttemptState | null;
    stale: boolean;
    sync_available_at: string | null;
    automatic_retry_blocked: boolean;
    total: number;
    offset: number;
  };
}): LoadedCatalogPage {
  return {
    models: data.models,
    catalog: {
      catalogId: data.catalog.catalog_id,
      catalogScope: data.catalog.catalog_scope,
      currentSnapshotId: data.catalog.current_snapshot_id,
      currentSnapshotCreatedAt: data.catalog.current_snapshot_created_at,
      latestAttempt: data.catalog.latest_attempt,
      stale: data.catalog.stale,
      syncAvailableAt: data.catalog.sync_available_at,
      automaticRetryBlocked: data.catalog.automatic_retry_blocked,
      total: data.catalog.total,
      loaded: data.catalog.offset + data.models.length,
    },
  };
}

export function ModelCatalogPickerContainer({
  opened,
  title,
  handle,
  integrations,
  selectedIntegrationId,
  selectedValue,
  onClose,
  onSelectIntegration,
  onSelectModel,
  onSyncCatalog,
}: ModelCatalogPickerContainerProps): React.ReactElement {
  const t = useTranslations("workspace.agents.modelCatalogPicker");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [pages, setPages] = useState<LoadedCatalogPage[]>([]);
  const [syncPending, setSyncPending] = useState(false);
  const [syncError, setSyncError] = useState<string | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const sentinelRef = useRef<HTMLDivElement | null>(null);
  const snapshotIdRef = useRef<string | null>(null);
  const snapshotObservedRef = useRef(false);

  const selectedIntegration =
    integrations.find(
      (integration) => integration.value === selectedIntegrationId,
    ) ?? null;
  const syncSupported = syncSupportedForIntegration(selectedIntegration);
  const catalog = pages.at(-1)?.catalog ?? null;
  const latestAttempt = catalog?.latestAttempt ?? null;
  const syncRunning = latestAttempt?.status === "running";
  const syncAvailableAt = catalog?.syncAvailableAt ?? null;
  const syncAvailableAtMillis =
    syncAvailableAt == null ? null : new Date(syncAvailableAt).getTime();
  const syncThrottled =
    syncAvailableAtMillis != null && syncAvailableAtMillis > clock;
  const canSync =
    selectedIntegration != null &&
    !selectedIntegration.disabled &&
    !syncRunning &&
    !syncPending &&
    !syncThrottled &&
    syncSupported;

  useEffect(() => {
    if (syncAvailableAtMillis == null || syncAvailableAtMillis <= Date.now()) {
      setClock(Date.now());
      return;
    }
    const timeout = window.setTimeout(() => {
      setClock(Date.now());
    }, syncAvailableAtMillis - Date.now());
    return () => window.clearTimeout(timeout);
  }, [syncAvailableAtMillis]);

  const query = trpc.llmProviderIntegration.listModels.useQuery(
    {
      handle,
      integrationId: selectedIntegrationId ?? "",
      search: search.trim() || void 0,
      limit: PAGE_SIZE,
      offset,
    },
    {
      enabled: opened && selectedIntegrationId != null,
      refetchInterval: (activeQuery) => {
        const activeCatalog = activeQuery.state.data?.catalog;
        if (
          activeCatalog == null ||
          activeCatalog.catalog_scope !== "integration"
        ) {
          return false;
        }
        if (activeCatalog.latest_attempt?.status === "running") {
          return 1_000;
        }
        if (!activeCatalog.stale || activeCatalog.automatic_retry_blocked) {
          return false;
        }
        if (activeCatalog.sync_available_at == null) {
          return 1_000;
        }
        return Math.max(
          new Date(activeCatalog.sync_available_at).getTime() - Date.now(),
          1_000,
        );
      },
    },
  );

  useEffect(() => {
    setOffset(0);
    setPages([]);
    snapshotIdRef.current = null;
    snapshotObservedRef.current = false;
  }, [opened, selectedIntegrationId, search]);

  useEffect(() => {
    if (query.data == null) {
      return;
    }
    const page = catalogStateFromPage(query.data);
    const snapshotChanged =
      snapshotObservedRef.current &&
      snapshotIdRef.current !== page.catalog.currentSnapshotId;
    snapshotIdRef.current = page.catalog.currentSnapshotId;
    snapshotObservedRef.current = true;
    if (query.data.catalog.offset !== 0 && snapshotChanged) {
      setOffset(0);
      setPages([]);
      return;
    }
    setPages((current) => {
      if (query.data.catalog.offset === 0) {
        return [page];
      }
      const pageIndex = current.findIndex(
        (item) => item.catalog.loaded === page.catalog.loaded,
      );
      if (pageIndex === -1) {
        return [...current, page];
      }
      return current.map((item, index) => (index === pageIndex ? page : item));
    });
  }, [query.data]);

  const models = useMemo(() => pages.flatMap((page) => page.models), [pages]);
  const hasNextPage = models.length < (catalog?.total ?? 0);

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (sentinel == null || !opened || !hasNextPage) {
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      const [entry] = entries;
      if (entry?.isIntersecting && !query.isFetching) {
        setOffset(models.length);
      }
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, models.length, opened, query.isFetching]);

  async function handleSyncCatalog(integrationId: string): Promise<void> {
    setSyncPending(true);
    setSyncError(null);
    try {
      await onSyncCatalog(integrationId);
    } catch (error) {
      setSyncError(error instanceof Error ? error.message : t("syncFailed"));
    } finally {
      setSyncPending(false);
    }
  }

  const state: ModelCatalogPickerState = {
    selectedIntegration,
    catalog,
    models,
    search,
    loading: query.isLoading,
    fetching: query.isFetching,
    hasLoadedPage: pages.length > 0,
    hasNextPage,
    syncSupported,
    canSync,
    syncRunning,
    syncPending,
    syncThrottled,
    syncAvailableAt,
    syncError,
    ui: catalogUiState({
      selectedIntegrationId,
      queryLoading: query.isLoading,
      queryFetching: query.isFetching,
      catalogState: catalog,
      models,
      hasNextPage,
    }),
  };

  return (
    <ModelCatalogPicker
      opened={opened}
      title={title}
      integrations={integrations}
      selectedIntegrationId={selectedIntegrationId}
      selectedValue={selectedValue}
      state={state}
      loadMoreRef={sentinelRef}
      onClose={onClose}
      onSelectIntegration={(integrationId) => {
        setSearch("");
        onSelectIntegration(integrationId);
      }}
      onSelectModel={onSelectModel}
      onSearchChange={setSearch}
      onSyncCatalog={(integrationId) => {
        void handleSyncCatalog(integrationId);
      }}
    />
  );
}
