"use client";

import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconCircleCheck, IconCircleX, IconServer } from "@tabler/icons-react";
import type {
  RuntimeProviderItem,
  RuntimeProvidersPageContentProps,
} from "../containers/useRuntimeProvidersPageContainer";

function statusColor(provider: RuntimeProviderItem): string {
  if (!provider.enabled || provider.lifecycle_state !== "active") {
    return "gray";
  }
  return provider.accepted_contract_revision_id ? "green" : "yellow";
}

function statusLabel(provider: RuntimeProviderItem): string {
  if (!provider.enabled) {
    return "Disabled";
  }
  if (provider.lifecycle_state !== "active") {
    return provider.lifecycle_state;
  }
  if (!provider.accepted_contract_revision_id) {
    return "Contract pending";
  }
  return "Ready for review";
}

function ProviderListItem({
  provider,
  selected,
  onSelect,
}: {
  provider: RuntimeProviderItem;
  selected: boolean;
  onSelect: () => void;
}): React.ReactElement {
  return (
    <Paper
      withBorder
      p="sm"
      radius="sm"
      bg={selected ? "var(--mantine-color-blue-light)" : "transparent"}
      style={{ cursor: "pointer" }}
      onClick={onSelect}
    >
      <Group justify="space-between" align="flex-start" wrap="nowrap">
        <Group gap="sm" wrap="nowrap">
          <IconServer size={18} />
          <Stack gap={2}>
            <Text fw={600}>{provider.display_name}</Text>
            <Text size="xs" c="dimmed" ff="monospace">
              {provider.provider_id}
            </Text>
          </Stack>
        </Group>
        <Badge color={statusColor(provider)} variant="light">
          {statusLabel(provider)}
        </Badge>
      </Group>
    </Paper>
  );
}

function ProviderDetail({
  provider,
  updating,
  onToggleEnabled,
}: {
  provider: RuntimeProviderItem;
  updating: boolean;
  onToggleEnabled: () => void;
}): React.ReactElement {
  return (
    <Stack gap="lg">
      <Group justify="space-between" align="flex-start">
        <Stack gap={3}>
          <Title order={3}>{provider.display_name}</Title>
          <Text size="sm" c="dimmed" ff="monospace">
            {provider.provider_id}
          </Text>
        </Stack>
        <Button
          variant={provider.enabled ? "light" : "filled"}
          color={provider.enabled ? "red" : "blue"}
          loading={updating}
          onClick={onToggleEnabled}
        >
          {provider.enabled ? "Disable Provider" : "Enable Provider"}
        </Button>
      </Group>

      <Group gap="xs">
        <Badge variant="light">{provider.kind}</Badge>
        <Badge variant="light">{provider.scope}</Badge>
        <Badge variant="light" color={statusColor(provider)}>
          {statusLabel(provider)}
        </Badge>
      </Group>

      <Divider />

      <Stack gap="sm">
        <Text size="sm" fw={600}>
          Operational state
        </Text>
        <Group grow align="flex-start">
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Lifecycle
            </Text>
            <Text>{provider.lifecycle_state}</Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Availability
            </Text>
            <Text>{provider.availability_mode}</Text>
          </Stack>
          <Stack gap={2}>
            <Text size="xs" c="dimmed">
              Admin version
            </Text>
            <Text>{provider.admin_version}</Text>
          </Stack>
        </Group>
      </Stack>

      <Stack gap="sm">
        <Text size="sm" fw={600}>
          Contract and configuration
        </Text>
        <Stack gap={4}>
          <Group gap="xs">
            {provider.accepted_contract_revision_id ? (
              <IconCircleCheck size={16} color="var(--mantine-color-green-6)" />
            ) : (
              <IconCircleX size={16} color="var(--mantine-color-yellow-6)" />
            )}
            <Text size="sm">
              {provider.accepted_contract_revision_id
                ? "Capability contract accepted"
                : "Capability contract requires Admin acceptance"}
            </Text>
          </Group>
          <Text size="sm" c="dimmed" ff="monospace">
            Config revision: {provider.active_config_revision_id ?? "None"}
          </Text>
        </Stack>
      </Stack>
    </Stack>
  );
}

export function RuntimeProvidersPageContent({
  state,
  selectedProvider,
  updating,
  errorMessage,
  onSelectProvider,
  onToggleEnabled,
}: RuntimeProvidersPageContentProps): React.ReactElement {
  return (
    <Stack gap="lg" p="md">
      <Stack gap={4}>
        <Title order={2}>Runtime Providers</Title>
        <Text c="dimmed">
          Inspect Provider readiness, contract state, and administrative policy.
        </Text>
      </Stack>

      {errorMessage && <Alert color="red">{errorMessage}</Alert>}

      {state.type === "LOADING" && <Loader />}
      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      {state.type === "LOADED" && state.items.length === 0 && (
        <Alert color="yellow" title="No Runtime Providers">
          Bootstrap or register a Provider before creating new Runtimes.
        </Alert>
      )}
      {state.type === "LOADED" && state.items.length > 0 && (
        <Paper withBorder radius="md" p={0} style={{ overflow: "hidden" }}>
          <Group align="stretch" gap={0} wrap="nowrap">
            <ScrollArea w={{ base: 260, sm: 340 }} p="sm" type="auto">
              <Stack gap="xs">
                {state.items.map((provider) => (
                  <ProviderListItem
                    key={provider.provider_id}
                    provider={provider}
                    selected={
                      provider.provider_id === selectedProvider?.provider_id
                    }
                    onSelect={() => onSelectProvider(provider.provider_id)}
                  />
                ))}
              </Stack>
            </ScrollArea>
            <Divider orientation="vertical" />
            <Stack p="xl" style={{ flex: 1, minWidth: 0 }}>
              {selectedProvider ? (
                <ProviderDetail
                  provider={selectedProvider}
                  updating={updating}
                  onToggleEnabled={() => onToggleEnabled(selectedProvider)}
                />
              ) : (
                <Text c="dimmed">Select a Provider to inspect its state.</Text>
              )}
            </Stack>
          </Group>
        </Paper>
      )}
    </Stack>
  );
}
