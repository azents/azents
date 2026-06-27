"use client";

import {
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  SimpleGrid,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconDatabase,
  IconRefresh,
} from "@tabler/icons-react";
import type { ModelCatalogPageContentProps } from "../containers/useModelCatalogPageContainer";
import type { SystemCatalogProvider, SystemCatalogStatus } from "../types";

const PROVIDER_LABELS: Record<SystemCatalogProvider, string> = {
  openai: "OpenAI",
  chatgpt_oauth: "ChatGPT OAuth",
  anthropic: "Anthropic",
  google_gemini: "Google Gemini",
};

function formatProvider(provider: string): string {
  switch (provider) {
    case "openai":
      return PROVIDER_LABELS.openai;
    case "chatgpt_oauth":
      return PROVIDER_LABELS.chatgpt_oauth;
    case "anthropic":
      return PROVIDER_LABELS.anthropic;
    case "google_gemini":
      return PROVIDER_LABELS.google_gemini;
    default:
      return provider;
  }
}

function formatSnapshot(snapshotId: string | null): string {
  return snapshotId ?? "No snapshot";
}

function CatalogStatusCard({
  status,
  allRefreshing,
  onRefreshCatalog,
}: {
  status: SystemCatalogStatus;
  allRefreshing: boolean;
  onRefreshCatalog: (provider: SystemCatalogProvider) => void;
}): React.ReactElement {
  const catalog = status.catalog;
  const refreshing = status.refreshing || allRefreshing;
  const disabled = refreshing;

  return (
    <Card withBorder shadow="sm" radius="md" p="md">
      <Stack gap="sm">
        <Group justify="space-between" align="flex-start">
          <Group gap="xs">
            <IconDatabase size={20} />
            <Title order={4}>{formatProvider(status.provider)}</Title>
          </Group>
          <Badge
            color={
              catalog?.latest_attempt?.status === "failed" ? "red" : "blue"
            }
          >
            {catalog?.latest_attempt?.status ?? "not synced"}
          </Badge>
        </Group>

        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            Catalog ID
          </Text>
          <Text size="sm" ff="monospace">
            {catalog?.catalog_id || "Not created yet"}
          </Text>
        </Stack>

        <Stack gap={4}>
          <Text size="sm" c="dimmed">
            Current snapshot
          </Text>
          <Text size="sm" ff="monospace">
            {formatSnapshot(catalog?.snapshot_id ?? null)}
          </Text>
        </Stack>

        <Group gap="xs">
          <Badge variant="light" color="green">
            Visible {catalog?.visible_count ?? 0}
          </Badge>
          <Badge variant="light" color="gray">
            Hidden {catalog?.hidden_count ?? 0}
          </Badge>
        </Group>

        {catalog?.latest_attempt?.failure_message && (
          <Alert
            color="red"
            title={catalog.latest_attempt.failure_code ?? "Refresh failed"}
          >
            {catalog.latest_attempt.failure_message}
            {catalog.latest_attempt.action_hint && (
              <Text size="sm" mt="xs">
                {catalog.latest_attempt.action_hint}
              </Text>
            )}
          </Alert>
        )}

        <Button
          leftSection={<IconRefresh size={16} />}
          loading={refreshing}
          disabled={disabled}
          onClick={() => onRefreshCatalog(status.provider)}
        >
          Refresh {formatProvider(status.provider)} catalog
        </Button>
      </Stack>
    </Card>
  );
}

export function ModelCatalogPageContent({
  state,
  catalogStatuses,
  allRefreshing,
  lastRefreshResult,
  lastBulkRefreshResults,
  refreshErrorMessage,
  onRefreshCatalog,
  onRefreshAllCatalogs,
}: ModelCatalogPageContentProps): React.ReactElement {
  return (
    <Stack gap="lg" p="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={4}>
          <Title order={2}>Model Catalog</Title>
          <Text c="dimmed">
            Trigger system model catalog refreshes by catalog provider.
          </Text>
        </Stack>
        <Button
          leftSection={<IconRefresh size={16} />}
          loading={allRefreshing}
          onClick={onRefreshAllCatalogs}
        >
          Refresh all system catalogs
        </Button>
      </Group>

      {refreshErrorMessage && (
        <Alert color="red" title="Refresh failed">
          {refreshErrorMessage}
        </Alert>
      )}

      {lastRefreshResult && (
        <Alert color="green" title="Catalog refresh completed">
          {formatProvider(lastRefreshResult.provider)} refreshed with{" "}
          {lastRefreshResult.visible_count} visible and{" "}
          {lastRefreshResult.hidden_count} hidden entries.
        </Alert>
      )}

      {lastBulkRefreshResults && (
        <Alert color="green" title="System catalog refresh completed">
          Refreshed {lastBulkRefreshResults.length} system catalogs.
        </Alert>
      )}

      {state.type === "LOADING" && (
        <Group justify="center" p="xl">
          <Loader />
        </Group>
      )}

      {state.type === "ERROR" && (
        <Alert
          color="red"
          icon={<IconAlertTriangle size={16} />}
          title="Unable to load system catalogs"
        >
          {state.message}
        </Alert>
      )}

      {state.type === "LOADED" && state.catalogs.length === 0 && (
        <Alert color="yellow" title="No system catalogs">
          No supported system catalog providers were returned by the admin API.
        </Alert>
      )}

      {state.type === "LOADED" && (
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          {catalogStatuses.map((status) => (
            <CatalogStatusCard
              key={status.provider}
              status={status}
              allRefreshing={allRefreshing}
              onRefreshCatalog={onRefreshCatalog}
            />
          ))}
        </SimpleGrid>
      )}
    </Stack>
  );
}
