"use client";

import {
  Alert,
  Badge,
  Box,
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
import { MasterDetailLayout } from "@/shared/components/MasterDetailLayout";
import { runtimeProviderReadiness } from "../runtimeProviderPresentation";
import type {
  RuntimeProviderAuthAuditState,
  RuntimeProviderAuthBindingItem,
  RuntimeProviderAuthBindingState,
  RuntimeProviderContractItem,
  RuntimeProviderContractState,
  RuntimeProviderItem,
  RuntimeProvidersPageContentProps,
} from "../containers/useRuntimeProvidersPageContainer";

function statusColor(provider: RuntimeProviderItem): string {
  return runtimeProviderReadiness(provider).color;
}

function statusLabel(provider: RuntimeProviderItem): string {
  return runtimeProviderReadiness(provider).label;
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
          <Stack gap={2} style={{ minWidth: 0 }}>
            <Text fw={600}>{provider.display_name}</Text>
            <Text
              size="xs"
              c="dimmed"
              ff="monospace"
              style={{ overflowWrap: "anywhere" }}
            >
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
              <Group justify="space-between" align="flex-start" wrap="wrap">
                <Stack gap={2} style={{ minWidth: 0 }}>
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
                  <Text
                    size="sm"
                    ff="monospace"
                    style={{ overflowWrap: "anywhere" }}
                  >
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

function ContractSection({
  provider,
  state,
  accepting,
  onAccept,
}: {
  provider: RuntimeProviderItem;
  state: RuntimeProviderContractState;
  accepting: boolean;
  onAccept: (contract: RuntimeProviderContractItem) => void;
}): React.ReactElement {
  const currentContract =
    state.type === "LOADED"
      ? (state.items.find(
          (contract) => contract.id === provider.current_contract_revision_id,
        ) ?? null)
      : null;
  const historicalContracts =
    state.type === "LOADED"
      ? state.items.filter(
          (contract) => contract.id !== provider.current_contract_revision_id,
        )
      : [];

  const contractCard = (
    contract: RuntimeProviderContractItem,
    current: boolean,
  ): React.ReactElement => (
    <Paper key={contract.id} withBorder p="sm" radius="sm">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Stack gap={2} style={{ minWidth: 0 }}>
          <Group gap="xs">
            {current && (
              <Badge color="blue" variant="light">
                Current advertisement
              </Badge>
            )}
            <Badge
              color={contract.status === "accepted" ? "green" : "yellow"}
              variant="light"
            >
              {contract.status}
            </Badge>
            <Text size="xs">
              Implementation {contract.implementation_version} · Protocol{" "}
              {contract.protocol_version}
            </Text>
          </Group>
          <Text
            size="xs"
            c="dimmed"
            ff="monospace"
            style={{ overflowWrap: "anywhere" }}
          >
            {contract.digest}
          </Text>
          {contract.validation_message && (
            <Text size="xs" c="red">
              {contract.validation_message}
            </Text>
          )}
        </Stack>
        {current &&
          contract.status === "candidate" &&
          contract.validation_code === null && (
            <Button
              size="xs"
              loading={accepting}
              onClick={() => onAccept(contract)}
            >
              Accept current contract
            </Button>
          )}
      </Group>
    </Paper>
  );

  return (
    <Stack gap="sm">
      <Text size="sm" fw={600}>
        Contract and configuration
      </Text>
      <Group gap="xs">
        {provider.current_contract_revision_id !== null &&
        provider.current_contract_revision_id ===
          provider.accepted_contract_revision_id ? (
          <IconCircleCheck size={16} color="var(--mantine-color-green-6)" />
        ) : (
          <IconCircleX size={16} color="var(--mantine-color-yellow-6)" />
        )}
        <Text size="sm">
          {provider.current_contract_revision_id === null
            ? "Waiting for the Provider to advertise a capability contract"
            : provider.current_contract_revision_id ===
                provider.accepted_contract_revision_id
              ? "Current capability contract accepted"
              : "Current capability contract requires Admin acceptance"}
        </Text>
      </Group>
      {state.type === "IDLE" && (
        <Text size="sm" c="dimmed">
          Select a Provider to inspect capability contracts.
        </Text>
      )}
      {state.type === "LOADING" && <Loader size="sm" />}
      {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
      {state.type === "LOADED" &&
        provider.current_contract_revision_id === null && (
          <Alert color="yellow">
            The connected Provider has not submitted a capability contract yet.
          </Alert>
        )}
      {state.type === "LOADED" &&
        provider.current_contract_revision_id !== null &&
        currentContract === null && (
          <Alert color="red">
            The current Provider advertisement is missing from contract history.
          </Alert>
        )}
      {currentContract !== null && contractCard(currentContract, true)}
      {historicalContracts.length > 0 && (
        <Stack gap="xs">
          <Text size="xs" fw={600} c="dimmed">
            Contract history
          </Text>
          {historicalContracts.map((contract) => contractCard(contract, false))}
        </Stack>
      )}
      <Text size="sm" c="dimmed" ff="monospace">
        Config revision: {provider.active_config_revision_id ?? "None"}
      </Text>
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
  contractState,
  authBindingState,
  authMutating,
  updating,
  acceptingContract,
  onToggleEnabled,
  onAcceptContract,
  onCreateAuthBinding,
  onRotateAuthBinding,
  onRevokeAuthBinding,
  onOpenAuthAudit,
}: {
  provider: RuntimeProviderItem;
  contractState: RuntimeProviderContractState;
  authBindingState: RuntimeProviderAuthBindingState;
  authMutating: boolean;
  updating: boolean;
  acceptingContract: boolean;
  onToggleEnabled: () => void;
  onAcceptContract: (contract: RuntimeProviderContractItem) => void;
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
          <Text
            size="sm"
            c="dimmed"
            ff="monospace"
            style={{ overflowWrap: "anywhere" }}
          >
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

      <ContractSection
        provider={provider}
        state={contractState}
        accepting={acceptingContract}
        onAccept={onAcceptContract}
      />

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
  detailOpen,
  contractState,
  authBindingState,
  authAuditState,
  authMutating,
  oneTimeSecret,
  updating,
  acceptingContract,
  errorMessage,
  onSelectProvider,
  onDetailClose,
  onToggleEnabled,
  onAcceptContract,
  onCreateAuthBinding,
  onRotateAuthBinding,
  onRevokeAuthBinding,
  onOpenAuthAudit,
  onCloseAuthAudit,
  onClearOneTimeSecret,
}: RuntimeProvidersPageContentProps): React.ReactElement {
  const master = (
    <ScrollArea h="100%" p="sm" type="auto">
      <Stack gap="xs">
        {state.type === "LOADED" &&
          state.items.map((provider) => (
            <ProviderListItem
              key={provider.provider_id}
              provider={provider}
              selected={provider.provider_id === selectedProvider?.provider_id}
              onSelect={() => onSelectProvider(provider.provider_id)}
            />
          ))}
      </Stack>
    </ScrollArea>
  );
  const detail = (
    <Stack p={{ base: "md", sm: "xl" }}>
      {selectedProvider ? (
        <ProviderDetail
          provider={selectedProvider}
          contractState={contractState}
          authBindingState={authBindingState}
          authMutating={authMutating}
          updating={updating}
          acceptingContract={acceptingContract}
          onToggleEnabled={() => onToggleEnabled(selectedProvider)}
          onAcceptContract={onAcceptContract}
          onCreateAuthBinding={onCreateAuthBinding}
          onRotateAuthBinding={onRotateAuthBinding}
          onRevokeAuthBinding={onRevokeAuthBinding}
          onOpenAuthAudit={onOpenAuthAudit}
        />
      ) : (
        <Text c="dimmed">Select a Provider to inspect its state.</Text>
      )}
    </Stack>
  );

  return (
    <Box h="100%" display="flex" style={{ flexDirection: "column" }}>
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

      <Stack gap={4} p="md">
        <Title order={2}>Runtime Providers</Title>
        <Text c="dimmed">
          Inspect Provider readiness, contract state, and administrative policy.
        </Text>
      </Stack>

      <Stack gap="sm" px="md">
        {errorMessage && <Alert color="red">{errorMessage}</Alert>}
        {state.type === "LOADING" && <Loader />}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
        {state.type === "LOADED" && state.items.length === 0 && (
          <Alert color="yellow" title="No Runtime Providers">
            Bootstrap or register a Provider before creating new Runtimes.
          </Alert>
        )}
      </Stack>
      {state.type === "LOADED" && state.items.length > 0 && (
        <Box px="md" pb="md" style={{ flex: 1, minHeight: 0 }}>
          <MasterDetailLayout
            columns="1fr 2fr"
            master={master}
            detail={detail}
            detailOpen={detailOpen}
            onDetailClose={onDetailClose}
          />
        </Box>
      )}
    </Box>
  );
}
