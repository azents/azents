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
import { formatLocalizedDate } from "@/shared/lib/date-format";
import {
  modelSupportsFunctionCalling,
  modelSupportsReasoning,
  supportedBuiltinTools,
} from "@/shared/lib/model-capability-support";
import { useLocale } from "@/shared/providers/locale";
import { modelContextBadgeValue } from "../model-selection";
import type {
  ModelCatalogState,
  ModelCatalogSyncStatus,
  ProviderIntegrationOption,
  SelectableModelCandidate,
} from "../model-selection";
import type { SupportedLocale } from "@/shared/lib/locale";
import type { Ref } from "react";

export type PickerCatalogUiState =
  | { type: "NO_INTEGRATION" }
  | { type: "LOADING_STATUS" }
  | { type: "NEVER_SYNCED" }
  | { type: "SYNCING_WITHOUT_DATA" }
  | { type: "FAILED_WITHOUT_DATA"; sync: ModelCatalogSyncStatus }
  | { type: "READY" }
  | { type: "READY_WITH_FAILED_SYNC"; sync: ModelCatalogSyncStatus }
  | { type: "READY_EMPTY" }
  | { type: "LOADING_NEXT_PAGE" };

export interface ModelCatalogPickerState {
  selectedIntegration: ProviderIntegrationOption | null;
  catalog: ModelCatalogState | null;
  models: SelectableModelCandidate[];
  search: string;
  loading: boolean;
  fetching: boolean;
  hasLoadedPage: boolean;
  hasNextPage: boolean;
  syncSupported: boolean;
  canSync: boolean;
  syncRunning: boolean;
  syncPending: boolean;
  syncThrottled: boolean;
  syncAvailableAt: string | null;
  syncError: string | null;
  ui: PickerCatalogUiState;
}

export interface ModelCatalogPickerProps {
  opened: boolean;
  title: string;
  integrations: ProviderIntegrationOption[];
  selectedIntegrationId: string | null;
  selectedValue: string | null;
  state: ModelCatalogPickerState;
  loadMoreRef?: Ref<HTMLDivElement>;
  onClose: () => void;
  onSelectIntegration: (integrationId: string) => void;
  onSelectModel: (model: SelectableModelCandidate) => void;
  onSearchChange: (search: string) => void;
  onSyncCatalog: (integrationId: string) => void;
}

function formatDate(
  value: string | null,
  neverLabel: string,
  locale: SupportedLocale,
): string {
  if (value == null) {
    return neverLabel;
  }
  return formatLocalizedDate(new Date(value), locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });
}

function formatCapabilityBadges(
  model: SelectableModelCandidate,
  labels: {
    context: (tokens: number) => string;
    contextRange: (defaultTokens: number, maxTokens: number) => string;
    reasoning: string;
    hostedTools: string;
    toolCalling: string;
  },
): string[] {
  const capabilities = model.normalized_capabilities;
  const badges: string[] = [];
  const contextBadge = modelContextBadgeValue(capabilities.context_window);
  if (contextBadge?.type === "RANGE") {
    badges.push(
      labels.contextRange(contextBadge.defaultTokens, contextBadge.maxTokens),
    );
  } else if (contextBadge?.type === "SINGLE") {
    badges.push(labels.context(contextBadge.tokens));
  }
  if (modelSupportsReasoning(capabilities)) {
    badges.push(labels.reasoning);
  }
  if (supportedBuiltinTools(capabilities).length > 0) {
    badges.push(labels.hostedTools);
  }
  if (modelSupportsFunctionCalling(capabilities)) {
    badges.push(labels.toolCalling);
  }
  return badges;
}

function modelSelectionValue(
  integrationId: string,
  model: SelectableModelCandidate,
): string {
  return `${integrationId}:${model.model_identifier}`;
}

function failureMessage(sync: ModelCatalogSyncStatus): string {
  return sync.failure_message ?? "The latest catalog sync failed.";
}

function catalogStatusTranslationKey(
  status: string | null,
):
  | "statusNeverSynced"
  | "statusRunning"
  | "statusSucceeded"
  | "statusFailed"
  | "statusUnknown" {
  switch (status) {
    case null:
      return "statusNeverSynced";
    case "running":
      return "statusRunning";
    case "succeeded":
      return "statusSucceeded";
    case "failed":
      return "statusFailed";
    default:
      return "statusUnknown";
  }
}

export function ModelCatalogPicker({
  opened,
  title,
  integrations,
  selectedIntegrationId,
  selectedValue,
  state,
  loadMoreRef,
  onClose,
  onSelectIntegration,
  onSelectModel,
  onSearchChange,
  onSyncCatalog,
}: ModelCatalogPickerProps): React.ReactElement {
  const t = useTranslations("workspace.agents.modelCatalogPicker");
  const { locale } = useLocale();
  const latestSync = state.catalog?.latestSync ?? null;

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
                onClick={() => onSelectIntegration(integration.value)}
              >
                {integration.label}
              </Button>
            ))}
          </Group>
        </Stack>

        {state.selectedIntegration == null ? (
          <Alert color="blue">{t("selectIntegrationFirst")}</Alert>
        ) : (
          <Card withBorder padding="sm">
            <Stack gap="xs">
              <Group justify="space-between" align="flex-start">
                <Stack gap={2}>
                  <Text fw={600}>{state.selectedIntegration.label}</Text>
                  <Text size="sm" c="dimmed">
                    {t("catalogStatus", {
                      status: t(
                        catalogStatusTranslationKey(latestSync?.status ?? null),
                      ),
                    })}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {t("lastSynced", {
                      value: formatDate(
                        state.catalog?.lastSuccessAt ?? null,
                        t("never"),
                        locale,
                      ),
                    })}
                  </Text>
                  <Text size="sm" c="dimmed">
                    {t("models", { count: state.catalog?.total ?? 0 })}
                  </Text>
                </Stack>
                {state.syncSupported && (
                  <Button
                    variant="light"
                    disabled={!state.canSync}
                    loading={state.syncRunning || state.syncPending}
                    onClick={() =>
                      onSyncCatalog(state.selectedIntegration?.value ?? "")
                    }
                  >
                    {state.syncRunning || state.syncPending
                      ? t("syncRunning")
                      : t("syncCatalog")}
                  </Button>
                )}
              </Group>
              {state.catalog?.catalogScope === "integration" &&
                state.catalog.stale &&
                !state.catalog.automaticRetryBlocked && (
                  <Alert color="blue">{t("staleRefreshQueued")}</Alert>
                )}
              {state.syncThrottled && state.syncAvailableAt != null && (
                <Alert color="gray">
                  {t("syncThrottledUntil", {
                    value: formatDate(
                      state.syncAvailableAt,
                      t("never"),
                      locale,
                    ),
                  })}
                </Alert>
              )}
              {state.syncError != null && (
                <Alert color="red">{state.syncError}</Alert>
              )}
              {state.ui.type === "READY_WITH_FAILED_SYNC" && (
                <Alert color="yellow" title={t("catalogSyncFailedTitle")}>
                  <Stack gap={4}>
                    <Text size="sm">{failureMessage(state.ui.sync)}</Text>
                    {state.ui.sync.action_hint && (
                      <Text size="sm">{state.ui.sync.action_hint}</Text>
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
          value={state.search}
          onChange={(event) => onSearchChange(event.currentTarget.value)}
          disabled={selectedIntegrationId == null}
        />

        <Stack gap="xs">
          {state.loading && !state.hasLoadedPage && (
            <Group justify="center" py="md">
              <Loader size="sm" />
            </Group>
          )}
          {state.ui.type === "FAILED_WITHOUT_DATA" && (
            <Alert color="red" title={t("catalogSyncFailedTitle")}>
              <Stack gap={4}>
                <Text size="sm">{failureMessage(state.ui.sync)}</Text>
                {state.ui.sync.action_hint && (
                  <Text size="sm">{state.ui.sync.action_hint}</Text>
                )}
              </Stack>
            </Alert>
          )}
          {state.ui.type === "NEVER_SYNCED" && (
            <Alert color="blue">{t("neverSynced")}</Alert>
          )}
          {state.ui.type === "SYNCING_WITHOUT_DATA" && (
            <Alert color="blue">{t("syncingWithoutData")}</Alert>
          )}
          {state.ui.type !== "FAILED_WITHOUT_DATA" &&
            state.models.map((model) => {
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
                          contextRange: (defaultTokens, maxTokens) =>
                            t("contextRangeBadge", {
                              defaultTokens,
                              maxTokens,
                            }),
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
          {state.ui.type === "READY_EMPTY" && (
            <Alert color="gray">{t("noModels")}</Alert>
          )}
          {state.hasNextPage && <div ref={loadMoreRef} />}
          {state.fetching && state.hasLoadedPage && (
            <Group justify="center" py="sm">
              <Loader size="xs" />
            </Group>
          )}
        </Stack>
      </Stack>
    </Modal>
  );
}
