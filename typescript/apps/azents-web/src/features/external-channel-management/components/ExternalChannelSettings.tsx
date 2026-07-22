"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Code,
  Divider,
  Group,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  rem,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconPlugConnected,
  IconRefresh,
  IconShieldCheck,
  IconShieldX,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ExternalChannelSettingsContainerOutput } from "../containers/useExternalChannelSettingsContainer";
import type { ConnectionDialogState, ManifestGuidanceState } from "../types";
import type {
  ExternalChannelConnectionStatus,
  ExternalChannelTransport,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
} from "@azents/public-client";

function statusColor(status: ExternalChannelConnectionStatus): string {
  switch (status) {
    case "active":
      return "green";
    case "degraded":
    case "reconnect_required":
      return "yellow";
    case "configuring":
    case "disconnecting":
      return "blue";
    case "disconnected":
      return "gray";
  }
}

function formatDate(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleString();
}

function capabilityEntries(
  capabilities: ManagedConnection["capabilities"],
): Array<[string, boolean]> {
  if (capabilities === null) {
    return [];
  }
  return Object.entries(capabilities).flatMap(([key, value]) =>
    typeof value === "boolean" ? [[key, value]] : [],
  );
}

function ConnectionRow({
  connection,
  busy,
  actionsBusy,
  onValidate,
  onSwitchTransport,
  onReconnect,
  onDisconnect,
}: {
  connection: ManagedConnection;
  busy: boolean;
  actionsBusy: boolean;
  onValidate: (connection: ManagedConnection) => void;
  onSwitchTransport: (
    connection: ManagedConnection,
    transport: ExternalChannelTransport,
  ) => void;
  onReconnect: (connection: ManagedConnection) => void;
  onDisconnect: (connection: ManagedConnection) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const capabilities = capabilityEntries(connection.capabilities);
  const terminal =
    connection.status === "disconnected" ||
    connection.status === "disconnecting";
  const nextTransport = connection.transport === "http" ? "socket" : "http";

  return (
    <Paper
      withBorder
      radius="lg"
      p="md"
      data-testid={`external-connection-${connection.id}`}
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={700}>{t("slack")}</Text>
              <Badge color={statusColor(connection.status)} variant="light">
                {t(`status.${connection.status}`)}
              </Badge>
              <Badge color="gray" variant="outline">
                {t(`transport.${connection.transport}`)}
              </Badge>
              <Badge
                color={connection.route_status === "active" ? "green" : "gray"}
                variant="dot"
              >
                {t(`route.${connection.route_status}`)}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed" mt={4}>
              {connection.provider_tenant_id ?? t("identityUnavailable")}
              {connection.provider_app_id
                ? ` · ${connection.provider_app_id}`
                : ""}
            </Text>
          </Box>
          <Badge
            color={connection.credentials_configured ? "green" : "red"}
            variant="light"
          >
            {connection.credentials_configured
              ? t("credentialsConfigured")
              : t("credentialsMissing")}
          </Badge>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <Box>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
              {t("lastVerified")}
            </Text>
            <Text size="sm">{formatDate(connection.last_verified_at)}</Text>
          </Box>
          <Box>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
              {t("lastHealth")}
            </Text>
            <Text size="sm">{formatDate(connection.last_health_at)}</Text>
          </Box>
          <Box>
            <Text size="xs" c="dimmed" tt="uppercase" fw={700}>
              {t("botIdentity")}
            </Text>
            <Text size="sm">{connection.provider_bot_user_id ?? "—"}</Text>
          </Box>
        </SimpleGrid>

        {connection.socket_gap_detected_at && (
          <Alert color="yellow" title={t("socketGapTitle")}>
            {connection.socket_gap_reason ?? t("socketGapDescription")}
          </Alert>
        )}

        <Group gap="xs">
          {capabilities.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("capabilitiesUnavailable")}
            </Text>
          ) : (
            capabilities.map(([name, enabled]) => (
              <Badge
                key={name}
                color={enabled ? "teal" : "gray"}
                variant="light"
              >
                {name.replaceAll("_", " ")}
              </Badge>
            ))
          )}
        </Group>

        <Group justify="flex-end" gap="xs">
          <Button
            variant="default"
            size="xs"
            loading={busy}
            disabled={actionsBusy || terminal}
            onClick={() => onValidate(connection)}
          >
            {t("validate")}
          </Button>
          <Button
            variant="default"
            size="xs"
            disabled={actionsBusy || terminal}
            onClick={() => onSwitchTransport(connection, nextTransport)}
          >
            {t("switchTransport", {
              transport: t(`transport.${nextTransport}`),
            })}
          </Button>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconRefresh size={rem(14)} />}
            disabled={actionsBusy}
            onClick={() => onReconnect(connection)}
          >
            {t("reconnect")}
          </Button>
          <Button
            color="red"
            variant="subtle"
            size="xs"
            leftSection={<IconTrash size={rem(14)} />}
            disabled={actionsBusy || terminal}
            onClick={() => {
              if (window.confirm(t("disconnectConfirm"))) {
                onDisconnect(connection);
              }
            }}
          >
            {t("disconnect")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function AccessRow({
  item,
  kind,
  busy,
  actionsBusy,
  onRemove,
}: {
  item: ManagedGrant | ManagedBlock;
  kind: "grant" | "block";
  busy: boolean;
  actionsBusy: boolean;
  onRemove: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const isGrant = kind === "grant";
  return (
    <Group
      justify="space-between"
      align="center"
      wrap="nowrap"
      py="sm"
      data-testid={`external-access-${kind}-${item.id}`}
    >
      <Group gap="sm" wrap="nowrap" style={{ minWidth: 0 }}>
        {isGrant ? (
          <IconShieldCheck
            size={rem(18)}
            color="var(--mantine-color-green-6)"
          />
        ) : (
          <IconShieldX size={rem(18)} color="var(--mantine-color-red-6)" />
        )}
        <Box style={{ minWidth: 0 }}>
          <Text fw={600} size="sm" truncate>
            {item.principal_label}
          </Text>
          <Text size="xs" c="dimmed" truncate>
            {isGrant && "scope" in item
              ? t(`grantScope.${item.scope}`)
              : "reason" in item
                ? item.reason || t("blockNoReason")
                : ""}
          </Text>
        </Box>
      </Group>
      <Button
        variant="subtle"
        color={isGrant ? "orange" : "gray"}
        size="xs"
        loading={busy}
        disabled={actionsBusy}
        onClick={() => {
          const key = isGrant ? "revokeConfirm" : "unblockConfirm";
          if (window.confirm(t(key))) {
            onRemove();
          }
        }}
      >
        {isGrant ? t("revoke") : t("unblock")}
      </Button>
    </Group>
  );
}

function ConnectionDialog({
  state,
  manifestState,
  actionError,
  saving,
  onChange,
  onClose,
  onSubmit,
}: {
  state: ConnectionDialogState;
  manifestState: ManifestGuidanceState;
  actionError: string | null;
  saving: boolean;
  onChange: (state: Exclude<ConnectionDialogState, null>) => void;
  onClose: () => void;
  onSubmit: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const disabled =
    state === null ||
    (state.type === "SETUP" && state.appId.trim() === "") ||
    state.credentials.botToken.trim() === "" ||
    state.credentials.signingSecret.trim() === "" ||
    (state.transport === "socket" && state.credentials.appToken.trim() === "");

  return (
    <Modal
      opened={state !== null}
      onClose={() => {
        if (!saving) {
          onClose();
        }
      }}
      title={
        state?.type === "RECONNECT" ? t("reconnectTitle") : t("setupTitle")
      }
      size="lg"
      closeOnClickOutside={!saving}
      closeOnEscape={!saving}
    >
      {state && (
        <Stack gap="md">
          {state.type === "SETUP" && (
            <>
              <TextInput
                label={t("appId")}
                value={state.appId}
                disabled={saving}
                onChange={(event) =>
                  onChange({ ...state, appId: event.currentTarget.value })
                }
              />
              <SegmentedControl
                fullWidth
                value={state.transport}
                disabled={saving}
                data={[
                  { value: "http", label: t("transport.http") },
                  { value: "socket", label: t("transport.socket") },
                ]}
                onChange={(value) =>
                  onChange({
                    ...state,
                    transport: value === "socket" ? "socket" : "http",
                  })
                }
              />
            </>
          )}
          {manifestState.type === "LOADING" && (
            <Center py="md">
              <Loader size="sm" />
            </Center>
          )}
          {manifestState.type === "ERROR" && (
            <Alert color="red">{manifestState.message}</Alert>
          )}
          {manifestState.type === "LOADED" && (
            <Paper withBorder radius="md" p="sm">
              <Stack gap="xs">
                <Text fw={700} size="sm">
                  {t("manifestTitle")}
                </Text>
                <Text size="xs" c="dimmed">
                  {t("botScopes")}
                </Text>
                <Code block>
                  {manifestState.manifest.bot_scopes.join(", ")}
                </Code>
                <Text size="xs" c="dimmed">
                  {t("eventSubscriptions")}
                </Text>
                <Code block>
                  {manifestState.manifest.event_subscriptions.join(", ")}
                </Code>
                {manifestState.manifest.app_token_scope && (
                  <Text size="xs">
                    {t("appTokenScope")}:{" "}
                    <Code>{manifestState.manifest.app_token_scope}</Code>
                  </Text>
                )}
                {manifestState.manifest.callback_path_template && (
                  <Text size="xs">
                    {t("callbackPath")}:{" "}
                    <Code>{manifestState.manifest.callback_path_template}</Code>
                  </Text>
                )}
              </Stack>
            </Paper>
          )}
          <PasswordInput
            label={t("botToken")}
            value={state.credentials.botToken}
            disabled={saving}
            onChange={(event) =>
              onChange({
                ...state,
                credentials: {
                  ...state.credentials,
                  botToken: event.currentTarget.value,
                },
              })
            }
          />
          <PasswordInput
            label={t("signingSecret")}
            value={state.credentials.signingSecret}
            disabled={saving}
            onChange={(event) =>
              onChange({
                ...state,
                credentials: {
                  ...state.credentials,
                  signingSecret: event.currentTarget.value,
                },
              })
            }
          />
          <PasswordInput
            label={t("appToken")}
            description={
              state.transport === "socket"
                ? t("appTokenRequired")
                : t("appTokenOptional")
            }
            value={state.credentials.appToken}
            disabled={saving}
            onChange={(event) =>
              onChange({
                ...state,
                credentials: {
                  ...state.credentials,
                  appToken: event.currentTarget.value,
                },
              })
            }
          />
          <Alert color="blue">{t("credentialSafety")}</Alert>
          {actionError && <Alert color="red">{actionError}</Alert>}
          <Group justify="flex-end">
            <Button variant="default" disabled={saving} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button loading={saving} disabled={disabled} onClick={onSubmit}>
              {state.type === "SETUP" ? t("connect") : t("replaceCredentials")}
            </Button>
          </Group>
        </Stack>
      )}
    </Modal>
  );
}

export function ExternalChannelSettings({
  state,
  manifestState,
  dialogState,
  actionError,
  actionTarget,
  actionsBusy,
  onOpenSetup,
  onOpenReconnect,
  onCloseDialog,
  onDialogChange,
  onSubmitDialog,
  onValidate,
  onSwitchTransport,
  onDisconnect,
  onRevokeGrant,
  onRemoveBlock,
}: ExternalChannelSettingsContainerOutput): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const loaded = state.type === "LOADED" ? state : null;

  return (
    <Box style={{ flex: 1, overflow: "auto", minHeight: 0 }}>
      <Stack gap="lg" p="md" maw={rem(960)} mx="auto" w="100%">
        <Group justify="space-between" align="flex-start">
          <Stack gap={4}>
            <Text fw={700} size="xl">
              {t("title")}
            </Text>
            <Text size="sm" c="dimmed">
              {t("description")}
            </Text>
          </Stack>
          <Button
            leftSection={<IconPlugConnected size={rem(16)} />}
            disabled={actionsBusy}
            onClick={onOpenSetup}
          >
            {t("addConnection")}
          </Button>
        </Group>

        {actionError && dialogState === null && (
          <Alert color="red">{actionError}</Alert>
        )}

        {state.type === "LOADING" && (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        )}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
        {loaded && (
          <>
            <Stack gap="sm">
              <Text fw={700}>{t("connectionsTitle")}</Text>
              {loaded.connections.length === 0 ? (
                <Paper withBorder radius="lg" p="xl">
                  <Stack align="center" gap="xs">
                    <Text fw={700}>{t("emptyConnectionsTitle")}</Text>
                    <Text size="sm" c="dimmed" ta="center">
                      {t("emptyConnectionsDescription")}
                    </Text>
                    <Button variant="light" onClick={onOpenSetup}>
                      {t("addConnection")}
                    </Button>
                  </Stack>
                </Paper>
              ) : (
                loaded.connections.map((connection) => (
                  <ConnectionRow
                    key={connection.id}
                    connection={connection}
                    busy={actionTarget === connection.id}
                    actionsBusy={actionsBusy}
                    onValidate={onValidate}
                    onSwitchTransport={onSwitchTransport}
                    onReconnect={onOpenReconnect}
                    onDisconnect={onDisconnect}
                  />
                ))
              )}
            </Stack>

            <Paper withBorder radius="lg" p="md">
              <Stack gap="sm">
                <Box>
                  <Text fw={700}>{t("accessTitle")}</Text>
                  <Text size="sm" c="dimmed">
                    {t("accessDescription")}
                  </Text>
                </Box>
                {loaded.grants.length === 0 && loaded.blocks.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    {t("emptyAccess")}
                  </Text>
                ) : (
                  <>
                    {loaded.grants.map((grant, index) => (
                      <Box key={grant.id}>
                        {index > 0 && <Divider />}
                        <AccessRow
                          item={grant}
                          kind="grant"
                          busy={actionTarget === grant.id}
                          actionsBusy={actionsBusy}
                          onRemove={() => onRevokeGrant(grant)}
                        />
                      </Box>
                    ))}
                    {loaded.grants.length > 0 && loaded.blocks.length > 0 && (
                      <Divider />
                    )}
                    {loaded.blocks.map((block, index) => (
                      <Box key={block.id}>
                        {index > 0 && <Divider />}
                        <AccessRow
                          item={block}
                          kind="block"
                          busy={actionTarget === block.id}
                          actionsBusy={actionsBusy}
                          onRemove={() => onRemoveBlock(block)}
                        />
                      </Box>
                    ))}
                  </>
                )}
              </Stack>
            </Paper>
          </>
        )}
      </Stack>
      <ConnectionDialog
        state={dialogState}
        manifestState={manifestState}
        actionError={actionError}
        saving={actionTarget === "dialog"}
        onChange={onDialogChange}
        onClose={onCloseDialog}
        onSubmit={onSubmitDialog}
      />
    </Box>
  );
}
