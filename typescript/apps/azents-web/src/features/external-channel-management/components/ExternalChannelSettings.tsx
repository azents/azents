"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Code,
  CopyButton,
  Divider,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  rem,
  SegmentedControl,
  SimpleGrid,
  Stack,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconCheck,
  IconCopy,
  IconPencil,
  IconPlugConnected,
  IconShieldCheck,
  IconShieldX,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { ExternalChannelSettingsContainerOutput } from "../containers/useExternalChannelSettingsContainer";
import type { ConnectionDialogState, ManifestGuidanceState } from "../types";
import type {
  ExternalChannelConnectionStatus,
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
  onEdit,
  onDisconnect,
}: {
  connection: ManagedConnection;
  busy: boolean;
  actionsBusy: boolean;
  onValidate: (connection: ManagedConnection) => void;
  onEdit: (connection: ManagedConnection) => void;
  onDisconnect: (connection: ManagedConnection) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const capabilities = capabilityEntries(connection.capabilities);

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

        {connection.transport === "socket" &&
          connection.socket_gap_detected_at && (
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
            disabled={actionsBusy}
            onClick={() => onValidate(connection)}
          >
            {t("validate")}
          </Button>
          <Button
            variant="light"
            size="xs"
            leftSection={<IconPencil size={rem(14)} />}
            disabled={actionsBusy}
            onClick={() => onEdit(connection)}
          >
            {t("edit")}
          </Button>
          <Button
            color="red"
            variant="subtle"
            size="xs"
            leftSection={<IconTrash size={rem(14)} />}
            disabled={actionsBusy}
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
          <Text fw={600} size="sm" style={{ overflowWrap: "anywhere" }}>
            {item.principal_label}
          </Text>
          <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
            {item.principal_provider_user_id}
          </Text>
          <Text size="xs" c="dimmed" style={{ overflowWrap: "anywhere" }}>
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

function CopyValueButton({
  value,
  label,
}: {
  value: string;
  label: string;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  return (
    <CopyButton value={value} timeout={1600}>
      {({ copied, copy }) => (
        <Button
          variant="light"
          size="xs"
          leftSection={
            copied ? <IconCheck size={rem(14)} /> : <IconCopy size={rem(14)} />
          }
          onClick={copy}
        >
          {copied ? t("copied") : label}
        </Button>
      )}
    </CopyButton>
  );
}

function GuideCodeBlock({
  children,
  mt,
}: {
  children: string;
  mt?: "xs";
}): React.ReactElement {
  return (
    <Box mt={mt} style={{ maxWidth: "100%", minWidth: 0 }}>
      <Code
        block
        style={{
          display: "block",
          maxWidth: "100%",
          minWidth: 0,
          overflowWrap: "anywhere",
          whiteSpace: "pre-wrap",
        }}
      >
        {children}
      </Code>
    </Box>
  );
}

function SlackAppGuide({
  manifestState,
}: {
  manifestState: ManifestGuidanceState;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");

  if (manifestState.type === "LOADING") {
    return (
      <Center py="md">
        <Loader size="sm" />
      </Center>
    );
  }
  if (manifestState.type === "ERROR") {
    return <Alert color="red">{manifestState.message}</Alert>;
  }
  if (manifestState.type !== "LOADED") {
    return <></>;
  }

  const { manifest } = manifestState;
  return (
    <Paper
      withBorder
      radius="md"
      p="md"
      style={{ maxWidth: "100%", minWidth: 0 }}
    >
      <Stack gap="md" style={{ minWidth: 0 }}>
        <Box>
          <Text fw={700}>{t("guideTitle")}</Text>
          <Text size="sm" c="dimmed">
            {t("guideDescription")}
          </Text>
        </Box>
        <Tabs defaultValue="manifest" style={{ minWidth: 0 }}>
          <Tabs.List grow style={{ minWidth: 0 }}>
            <Tabs.Tab
              value="manifest"
              style={{ minWidth: 0, whiteSpace: "normal" }}
            >
              {t("manifestMethod")}
            </Tabs.Tab>
            <Tabs.Tab
              value="manual"
              style={{ minWidth: 0, whiteSpace: "normal" }}
            >
              {t("manualMethod")}
            </Tabs.Tab>
          </Tabs.List>

          <Tabs.Panel value="manifest" pt="md">
            <Stack gap="sm">
              <Text size="sm">{t("manifestIntro")}</Text>
              <List type="ordered" size="sm" spacing="xs">
                <List.Item>{t("manifestStep1")}</List.Item>
                <List.Item>{t("manifestStep2")}</List.Item>
                <List.Item>{t("manifestStep3")}</List.Item>
                <List.Item>{t("manifestStep4")}</List.Item>
              </List>
              <Group justify="space-between">
                <Text fw={700} size="sm">
                  {t("manifestJson")}
                </Text>
                <CopyValueButton
                  value={manifest.manifest_json}
                  label={t("copyManifest")}
                />
              </Group>
              <GuideCodeBlock>{manifest.manifest_json}</GuideCodeBlock>
            </Stack>
          </Tabs.Panel>

          <Tabs.Panel value="manual" pt="md">
            <Stack gap="sm">
              <Text size="sm">{t("manualIntro")}</Text>
              <List type="ordered" size="sm" spacing="xs">
                <List.Item>{t("manualStep1")}</List.Item>
                <List.Item>
                  {t("manualStep2")}
                  <GuideCodeBlock mt="xs">
                    {manifest.bot_scopes.join(", ")}
                  </GuideCodeBlock>
                </List.Item>
                <List.Item>
                  {manifest.transport === "http"
                    ? t("manualHttpStep")
                    : t("manualSocketEventsStep")}
                  {manifest.callback_url && (
                    <Stack gap="xs" mt="xs">
                      <GuideCodeBlock>{manifest.callback_url}</GuideCodeBlock>
                      <Group justify="flex-end">
                        <CopyValueButton
                          value={manifest.callback_url}
                          label={t("copyCallback")}
                        />
                      </Group>
                    </Stack>
                  )}
                  <GuideCodeBlock mt="xs">
                    {manifest.event_subscriptions.join(", ")}
                  </GuideCodeBlock>
                </List.Item>
                {manifest.transport === "socket" && (
                  <List.Item>{t("manualSocketStep")}</List.Item>
                )}
                <List.Item>{t("manualInstallStep")}</List.Item>
                <List.Item>{t("manualInviteStep")}</List.Item>
              </List>
              <Alert color="blue">{t("reinstallNotice")}</Alert>
            </Stack>
          </Tabs.Panel>
        </Tabs>

        <Divider />
        <Box>
          <Text fw={700} size="sm">
            {t("credentialLocationsTitle")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("credentialLocationsDescription")}
          </Text>
        </Box>
        <List size="sm" spacing="xs">
          <List.Item>{t("appIdLocation")}</List.Item>
          <List.Item>{t("signingSecretLocation")}</List.Item>
          <List.Item>{t("botTokenLocation")}</List.Item>
          {manifest.transport === "socket" && (
            <List.Item>{t("appTokenLocation")}</List.Item>
          )}
        </List>
        <Alert color="yellow">{t("tokenPrefixes")}</Alert>
      </Stack>
    </Paper>
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
    state.appId.trim() === "" ||
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
      title={state?.type === "EDIT" ? t("editTitle") : t("setupTitle")}
      size="xl"
      closeOnClickOutside={!saving}
      closeOnEscape={!saving}
      styles={{
        body: { overflowX: "hidden" },
        content: { overflowX: "hidden" },
      }}
    >
      {state && (
        <Stack gap="md" style={{ minWidth: 0 }}>
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
          <SlackAppGuide manifestState={manifestState} />
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
              {state.type === "SETUP" ? t("connect") : t("saveChanges")}
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
  onOpenEdit,
  onCloseDialog,
  onDialogChange,
  onSubmitDialog,
  onValidate,
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
                    onEdit={onOpenEdit}
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
