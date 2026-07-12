"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslations } from "next-intl";
import { useEffect, useMemo, useRef, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  ModelCatalogAttemptState,
  ModelCatalogState,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "../model-selection";

const PAGE_SIZE = 50;

export interface ModelCatalogPickerProps {
  opened: boolean;
  title: string;
  handle: string;
  integrations: ProviderIntegrationOption[];
  selectedIntegrationId: string | null;
  selectedValue: string | null;
  onClose: () => void;
  onSelectIntegration: (integrationId: string) => void;
  onSelectModel: (model: SelectableModelCandidate) => void;
  onSyncCatalog: (integrationId: string) => void;
}

interface LoadedCatalogPage {
  models: SelectableModelCandidate[];
  catalog: ModelCatalogState;
}

type PickerCatalogUiState =
  | { type: "NO_INTEGRATION" }
  | { type: "LOADING_STATUS" }
  | { type: "NEVER_SYNCED" }
  | { type: "SYNCING_WITHOUT_SNAPSHOT" }
  | { type: "FAILED_WITHOUT_SNAPSHOT"; attempt: ModelCatalogAttemptState }
  | { type: "READY" }
  | { type: "READY_WITH_FAILED_ATTEMPT"; attempt: ModelCatalogAttemptState }
  | { type: "READY_EMPTY" }
  | { type: "LOADING_NEXT_PAGE" };

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

function formatDate(value: string | null, neverLabel: string): string {
  if (value == null) {
    return neverLabel;
  }
  return new Intl.DateTimeFormat([], {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

function formatCapabilityBadges(
  model: SelectableModelCandidate,
  labels: {
    context: (tokens: number) => string;
    reasoning: string;
    hostedTools: string;
    toolCalling: string;
  },
): string[] {
  const capabilities = model.normalized_capabilities;
  const badges: string[] = [];
  const context = capabilities.context_window?.max_input_tokens;
  if (typeof context === "number") {
    badges.push(labels.context(Math.round(context / 1000)));
  }
  if (capabilities.reasoning?.supported) {
    badges.push(labels.reasoning);
  }
  if ((capabilities.built_in_tools?.supported ?? []).length > 0) {
    badges.push(labels.hostedTools);
  }
  if (capabilities.tool_calling?.supported) {
    badges.push(labels.toolCalling);
  }
  return badges;
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
    integration.provider === "google_vertex_ai"
  );
}

function modelSelectionValue(
  integrationId: string,
  model: SelectableModelCandidate,
): string {
  return `${integrationId}:${model.model_identifier}`;
}

function failureMessage(attempt: ModelCatalogAttemptState): string {
  return attempt.failure_message ?? "The latest catalog sync failed.";
}

export function ModelCatalogPicker({
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
}: ModelCatalogPickerProps): React.ReactElement {
  const t = useTranslations("workspace.agents.modelCatalogPicker");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [pages, setPages] = useState<LoadedCatalogPage[]>([]);
  const sentinelRef = useRef<HTMLDivElement | null>(null);

  const selectedIntegration = integrations.find(
    (integration) => integration.value === selectedIntegrationId,
  );
  const selectedIntegrationOrNull = selectedIntegration ?? null;
  const syncSupported = syncSupportedForIntegration(selectedIntegrationOrNull);
  const catalogState = pages.at(-1)?.catalog ?? null;
  const latestAttempt = catalogState?.latestAttempt ?? null;
  const syncRunning = latestAttempt?.status === "running";
  const canSync =
    selectedIntegrationOrNull != null &&
    !selectedIntegrationOrNull.disabled &&
    !syncRunning &&
    syncSupported;

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
    },
  );

  useEffect(() => {
    setOffset(0);
    setPages([]);
  }, [opened, selectedIntegrationId, search]);

  useEffect(() => {
    if (query.data == null) {
      return;
    }
    const page: LoadedCatalogPage = {
      models: query.data.models,
      catalog: {
        catalogId: query.data.catalog.catalog_id,
        currentSnapshotId: query.data.catalog.current_snapshot_id,
        currentSnapshotCreatedAt:
          query.data.catalog.current_snapshot_created_at,
        latestAttempt: query.data.catalog.latest_attempt,
        total: query.data.catalog.total,
        loaded: query.data.catalog.offset + query.data.models.length,
      },
    };
    setPages((current) => {
      if (query.data.catalog.offset === 0) {
        return [page];
      }
      if (current.some((item) => item.catalog.loaded === page.catalog.loaded)) {
        return current;
      }
      return [...current, page];
    });
  }, [query.data]);

  const models = useMemo(() => pages.flatMap((page) => page.models), [pages]);
  const loadedCount = models.length;
  const total = catalogState?.total ?? 0;
  const hasNextPage = loadedCount < total;

  useEffect(() => {
    const sentinel = sentinelRef.current;
    if (sentinel == null || !opened || !hasNextPage) {
      return;
    }
    const observer = new IntersectionObserver((entries) => {
      const [entry] = entries;
      if (entry?.isIntersecting && !query.isFetching) {
        setOffset(loadedCount);
      }
    });
    observer.observe(sentinel);
    return () => observer.disconnect();
  }, [hasNextPage, loadedCount, opened, query.isFetching]);

  const uiState = catalogUiState({
    selectedIntegrationId,
    queryLoading: query.isLoading,
    queryFetching: query.isFetching,
    catalogState,
    models,
    hasNextPage,
  });

  return (
    <Modal opened={opened} onClose={onClose} title={title} size="xl">
      <Stack gap="md">
        <Stack gap="xs">
          <Text size="sm" fw={600}>
            {t("providerIntegration")}
          </Text>
          <Group gap="xs">
            {integrations.map((integration) => (
              <Button
                key={integration.value}
                variant={
                  integration.value === selectedIntegrationId
                    ? "filled"
                    : "light"
                }
                disabled={integration.disabled}
                onClick={() => {
                  onSelectIntegration(integration.value);
                  setSearch("");
                }}
              >
                {integration.label}
              </Button>
            ))}
          </Group>
        </Stack>

        {selectedIntegrationOrNull == null ? (
          <Alert color="blue">{t("selectIntegrationFirst")}</Alert>
        ) : (
          <Card withBorder padding="sm">
            <Stack gap="xs">
              <Group justify="space-between" align="flex-start">
                <Stack gap={2}>
                  <Text fw={600}>{selectedIntegrationOrNull.label}</Text>
                  <Text size="sm" c="dimmed">
                    {t("catalogStatus", {
                      status: latestAttempt?.status ?? t("statusNeverSynced"),
                    })}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {t("lastSynced", {
                      value: formatDate(
                        catalogState?.currentSnapshotCreatedAt ?? null,
                        t("never"),
                      ),
                    })}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {t("models", { count: catalogState?.total ?? 0 })}
                  </Text>
                </Stack>
                {syncSupported && (
                  <Button
                    variant="light"
                    disabled={!canSync}
                    loading={syncRunning}
                    onClick={() =>
                      onSyncCatalog(selectedIntegrationOrNull.value)
                    }
                  >
                    {syncRunning ? t("syncRunning") : t("syncCatalog")}
                  </Button>
                )}
              </Group>
              {uiState.type === "READY_WITH_FAILED_ATTEMPT" && (
                <Alert color="yellow" title={t("catalogSyncFailedTitle")}>
                  <Stack gap={4}>
                    <Text size="sm">{failureMessage(uiState.attempt)}</Text>
                    {uiState.attempt.action_hint && (
                      <Text size="sm">{uiState.attempt.action_hint}</Text>
                    )}
                  </Stack>
                </Alert>
              )}
            </Stack>
          </Card>
        )}

        <TextInput
          label={t("searchLabel")}
          placeholder={t("searchPlaceholder")}
          value={search}
          onChange={(event) => setSearch(event.currentTarget.value)}
          disabled={selectedIntegrationId == null}
        />

        <Stack gap="xs">
          {query.isLoading && pages.length === 0 && (
            <Group justify="center" py="md">
              <Loader size="sm" />
            </Group>
          )}
          {uiState.type === "FAILED_WITHOUT_SNAPSHOT" && (
            <Alert color="red" title={t("catalogSyncFailedTitle")}>
              <Stack gap={4}>
                <Text size="sm">{failureMessage(uiState.attempt)}</Text>
                {uiState.attempt.action_hint && (
                  <Text size="sm">{uiState.attempt.action_hint}</Text>
                )}
              </Stack>
            </Alert>
          )}
          {uiState.type === "NEVER_SYNCED" && (
            <Alert color="blue">{t("neverSynced")}</Alert>
          )}
          {uiState.type === "SYNCING_WITHOUT_SNAPSHOT" && (
            <Alert color="blue">{t("syncingWithoutSnapshot")}</Alert>
          )}
          {uiState.type !== "FAILED_WITHOUT_SNAPSHOT" &&
            models.map((model) => {
              const value = modelSelectionValue(
                selectedIntegrationId ?? "",
                model,
              );
              return (
                <Card
                  key={value}
                  withBorder
                  padding="sm"
                  style={
                    value === selectedValue
                      ? { borderColor: "var(--mantine-color-blue-6)" }
                      : {}
                  }
                >
                  <Group justify="space-between" align="flex-start">
                    <Stack gap={6}>
                      <Text fw={600}>{model.model_display_name}</Text>
                      <Text size="sm" c="dimmed">
                        {model.model_identifier}
                      </Text>
                      <Group gap={6}>
                        {formatCapabilityBadges(model, {
                          context: (tokens) => t("contextBadge", { tokens }),
                          reasoning: t("reasoningBadge"),
                          hostedTools: t("hostedToolsBadge"),
                          toolCalling: t("toolCallingBadge"),
                        }).map((badge) => (
                          <Badge key={badge} variant="light">
                            {badge}
                          </Badge>
                        ))}
                      </Group>
                    </Stack>
                    <Button
                      variant={value === selectedValue ? "filled" : "light"}
                      onClick={() => {
                        onSelectModel(model);
                        onClose();
                      }}
                    >
                      {value === selectedValue ? t("selected") : t("select")}
                    </Button>
                  </Group>
                </Card>
              );
            })}
          {uiState.type === "READY_EMPTY" && (
            <Alert color="gray">{t("noModels")}</Alert>
          )}
          {hasNextPage && <div ref={sentinelRef} />}
          {query.isFetching && pages.length > 0 && (
            <Group justify="center" py="sm">
              <Loader size="xs" />
            </Group>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
}
