"use client";

import {
  Alert,
  Badge,
  Button,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconCircleCheck, IconCircleX, IconServer } from "@tabler/icons-react";
import type {
  RuntimeProviderAuthAuditState,
  RuntimeProviderAuthBindingItem,
  RuntimeProviderAuthBindingState,
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

function AuthenticationSection({
  state,
  mutating,
  onCreate,
  onRotate,
  onRevoke,
  onViewAudit,
}: {
  state: RuntimeProviderAuthBindingState;
  mutating: boolean;
  onCreate: () => void;
  onRotate: (binding: RuntimeProviderAuthBindingItem) => void;
  onRevoke: (binding: RuntimeProviderAuthBindingItem) => void;
  onViewAudit: (binding: RuntimeProviderAuthBindingItem) => void;
}): React.ReactElement {
  return (
    <Stack gap="sm">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Text size="sm" fw={600}>
            Authentication
          </Text>
          <Text size="xs" c="dimmed">
            Binding identity, lifecycle, ownership, and connection health.
          </Text>
        </Stack>
        <Button size="xs" variant="light" loading={mutating} onClick={onCreate}>
          Create issued-token binding
        </Button>
      </Group>

      {state.type === "IDLE" && (
        <Text size="sm" c="dimmed">
          Select a Provider to inspect authentication.
        </Text>
      )}
      {state.type === "LOADING" && <Loader size="sm" />}
      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      {state.type === "LOADED" && state.items.length === 0 && (
        <Alert color="yellow">No authentication bindings.</Alert>
      )}
      {state.type === "LOADED" &&
        state.items.map((binding) => (
          <Paper key={binding.id} withBorder p="sm" radius="sm">
            <Stack gap="xs">
              <Group justify="space-between" align="flex-start" wrap="nowrap">
                <Stack gap={2}>
                  <Group gap="xs">
                    <Badge variant="light">{binding.auth_method}</Badge>
                    <Badge
                      color={binding.state === "active" ? "green" : "gray"}
                      variant="light"
                    >
                      {binding.state}
                    </Badge>
                    <Badge
                      color={binding.connected ? "blue" : "gray"}
                      variant="light"
                    >
                      {binding.connected ? "Connected" : "Disconnected"}
                    </Badge>
                  </Group>
                  <Text size="sm" ff="monospace">
                    {binding.subject}
                  </Text>
                  <Text size="xs" c="dimmed">
                    Owner: {binding.owner} · Version {binding.admin_version}
                  </Text>
                </Stack>
                <Group gap="xs">
                  <Button
                    size="xs"
                    variant="subtle"
                    onClick={() => onViewAudit(binding)}
                  >
                    Audit
                  </Button>
                  {binding.owner === "admin" && binding.state === "active" && (
                    <>
                      <Button
                        size="xs"
                        variant="light"
                        loading={mutating}
                        onClick={() => onRotate(binding)}
                      >
                        Rotate
                      </Button>
                      <Button
                        size="xs"
                        color="red"
                        variant="light"
                        loading={mutating}
                        onClick={() => onRevoke(binding)}
                      >
                        Revoke
                      </Button>
                    </>
                  )}
                </Group>
              </Group>
              {binding.owner === "bootstrap" && (
                <Text size="xs" c="dimmed">
                  Managed by bootstrap declaration. Admin actions are read-only.
                </Text>
              )}
              <Text size="xs" c="dimmed">
                Last authenticated: {binding.last_authenticated_at ?? "Never"} ·
                Last connected: {binding.last_connected_at ?? "Never"}
              </Text>
            </Stack>
          </Paper>
        ))}
    </Stack>
  );
}

function AuthenticationAudit({
  state,
}: {
  state: RuntimeProviderAuthAuditState;
}): React.ReactElement | null {
  switch (state.type) {
    case "IDLE":
      return null;
    case "LOADING":
      return <Loader size="sm" />;
    case "ERROR":
      return <Alert color="red">{state.message}</Alert>;
    case "LOADED":
      return (
        <Stack gap="sm">
          <Text size="sm" ff="monospace">
            {state.binding.subject}
          </Text>
          {state.items.length === 0 && (
            <Alert color="yellow">No audit events.</Alert>
          )}
          {state.items.map((event) => (
            <Paper key={event.id} withBorder p="sm" radius="sm">
              <Stack gap={2}>
                <Group justify="space-between">
                  <Badge variant="light">{event.event_type}</Badge>
                  <Text size="xs" c="dimmed">
                    {event.created_at}
                  </Text>
                </Group>
                <Text size="xs" c="dimmed">
                  Actor: {event.actor_user_id ?? "System"} · Version:{" "}
                  {event.previous_admin_version ?? "—"} →{" "}
                  {event.new_admin_version ?? "—"}
                </Text>
                {event.metadata && (
                  <Text size="xs" ff="monospace">
                    {JSON.stringify(event.metadata)}
                  </Text>
                )}
              </Stack>
            </Paper>
          ))}
        </Stack>
      );
  }
}

function ProviderDetail({
  provider,
  authBindingState,
  authMutating,
  updating,
  onToggleEnabled,
  onCreateAuthBinding,
  onRotateAuthBinding,
  onRevokeAuthBinding,
  onOpenAuthAudit,
}: {
  provider: RuntimeProviderItem;
  authBindingState: RuntimeProviderAuthBindingState;
  authMutating: boolean;
  updating: boolean;
  onToggleEnabled: () => void;
  onCreateAuthBinding: () => void;
  onRotateAuthBinding: (binding: RuntimeProviderAuthBindingItem) => void;
  onRevokeAuthBinding: (binding: RuntimeProviderAuthBindingItem) => void;
  onOpenAuthAudit: (binding: RuntimeProviderAuthBindingItem) => void;
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

      <Divider />
      <AuthenticationSection
        state={authBindingState}
        mutating={authMutating}
        onCreate={onCreateAuthBinding}
        onRotate={onRotateAuthBinding}
        onRevoke={onRevokeAuthBinding}
        onViewAudit={onOpenAuthAudit}
      />
    </Stack>
  );
}

export function RuntimeProvidersPageContent({
  state,
  selectedProvider,
  authBindingState,
  authAuditState,
  authMutating,
  oneTimeSecret,
  updating,
  errorMessage,
  onSelectProvider,
  onToggleEnabled,
  onCreateAuthBinding,
  onRotateAuthBinding,
  onRevokeAuthBinding,
  onOpenAuthAudit,
  onCloseAuthAudit,
  onClearOneTimeSecret,
}: RuntimeProvidersPageContentProps): React.ReactElement {
  return (
    <Stack gap="lg" p="md">
      <Modal
        opened={oneTimeSecret !== null}
        onClose={onClearOneTimeSecret}
        title="One-time enrollment secret"
      >
        <Stack gap="sm">
          <Alert color="yellow">
            Copy this secret now. It cannot be displayed again.
          </Alert>
          <Text ff="monospace" style={{ overflowWrap: "anywhere" }}>
            {oneTimeSecret?.secret}
          </Text>
          <Button onClick={onClearOneTimeSecret}>Done</Button>
        </Stack>
      </Modal>
      <Modal
        opened={authAuditState.type !== "IDLE"}
        onClose={onCloseAuthAudit}
        title="Authentication audit"
      >
        <AuthenticationAudit state={authAuditState} />
      </Modal>

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
                  authBindingState={authBindingState}
                  authMutating={authMutating}
                  updating={updating}
                  onToggleEnabled={() => onToggleEnabled(selectedProvider)}
                  onCreateAuthBinding={onCreateAuthBinding}
                  onRotateAuthBinding={onRotateAuthBinding}
                  onRevokeAuthBinding={onRevokeAuthBinding}
                  onOpenAuthAudit={onOpenAuthAudit}
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
