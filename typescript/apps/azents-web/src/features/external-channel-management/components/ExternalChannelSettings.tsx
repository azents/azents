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
  Flex,
  Group,
  List,
  Loader,
  Modal,
  Paper,
  PasswordInput,
  Radio,
  rem,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Switch,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import { useModals } from "@mantine/modals";
import {
  IconBrandDiscord,
  IconBrandSlack,
  IconCheck,
  IconCopy,
  IconPencil,
  IconSettings,
  IconShieldCheck,
  IconShieldX,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { DiscordSetupGuide } from "@/shared/components/DiscordSetupGuide";
import {
  discordThreadAutoArchiveDurationFromConfiguration,
  discordThreadAutoArchiveDurationFromSelectValue,
} from "@/shared/lib/discord-thread-auto-archive-duration";
import { isOneOf } from "@/shared/lib/unknown-value";
import type { ExternalChannelSettingsContainerOutput } from "../containers/useExternalChannelSettingsContainer";
import type {
  ConnectionDialogState,
  DiscordConnectionDialogState,
  ManifestGuidanceState,
} from "../types";
import type {
  DiscordThreadAutoArchiveDurationMinutes,
  ExternalChannelConnectionStatus,
  ManagedBlock,
  ManagedConnection,
  ManagedGrant,
  ManagedMultiConnection,
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

const DISCORD_FAILURE_CODES = [
  "discord_credentials_invalid",
  "discord_callback_configuration_invalid",
  "discord_api_unavailable",
  "discord_callback_url_missing",
  "discord_credentials_unavailable",
  "discord_target_guild_missing",
  "discord_target_guild_invalid",
  "discord_application_id_mismatch",
  "discord_authority_changed",
] as const;

type DiscordFailureCode = (typeof DISCORD_FAILURE_CODES)[number];

function discordFailureCode(
  value: string | null,
): DiscordFailureCode | "unknown" {
  return isOneOf(value, DISCORD_FAILURE_CODES) ? value : "unknown";
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

function DiscordThreadAutoArchiveDurationSelect({
  value,
  disabled,
  onChange,
}: {
  value: DiscordThreadAutoArchiveDurationMinutes;
  disabled: boolean;
  onChange: (value: DiscordThreadAutoArchiveDurationMinutes) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");

  return (
    <Select
      label={t("discordThreadAutoArchiveDuration")}
      value={String(value)}
      disabled={disabled}
      data={[
        {
          value: "60",
          label: t("discordThreadAutoArchiveDurationOptions.oneHour"),
        },
        {
          value: "1440",
          label: t("discordThreadAutoArchiveDurationOptions.oneDay"),
        },
        {
          value: "4320",
          label: t("discordThreadAutoArchiveDurationOptions.threeDays"),
        },
        {
          value: "10080",
          label: t("discordThreadAutoArchiveDurationOptions.sevenDays"),
        },
      ]}
      onChange={(selected) => {
        const duration =
          discordThreadAutoArchiveDurationFromSelectValue(selected);
        if (duration !== null) {
          onChange(duration);
        }
      }}
    />
  );
}

function ConnectionRow({
  connection,
  busy,
  actionsBusy,
  discordThreadDurationDraft,
  discordThreadDurationSaved,
  onValidate,
  onEdit,
  onDisconnect,
  onUpdateAccessPolicy,
  onDiscordThreadDurationChange,
  onSaveDiscordThreadDuration,
}: {
  connection: ManagedConnection;
  busy: boolean;
  actionsBusy: boolean;
  discordThreadDurationDraft: DiscordThreadAutoArchiveDurationMinutes;
  discordThreadDurationSaved: boolean;
  onValidate: (connection: ManagedConnection) => void;
  onEdit: (connection: ManagedConnection) => void;
  onDisconnect: (connection: ManagedConnection) => void;
  onUpdateAccessPolicy: (
    connection: ManagedConnection,
    openAccessEnabled: boolean,
  ) => void;
  onDiscordThreadDurationChange: (
    duration: DiscordThreadAutoArchiveDurationMinutes,
  ) => void;
  onSaveDiscordThreadDuration: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const capabilities = capabilityEntries(connection.capabilities);
  const currentDiscordThreadDuration =
    discordThreadAutoArchiveDurationFromConfiguration(
      connection.provider_config,
    );

  return (
    <Paper
      withBorder
      radius="lg"
      p="md"
      data-testid={`external-connection-${connection.id}`}
    >
      <Stack gap="md">
        <Flex
          direction={{ base: "column", sm: "row" }}
          justify="space-between"
          align="flex-start"
          gap="xs"
        >
          <Box w={{ base: "100%", sm: "auto" }} style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={700}>
                {connection.provider === "discord" ? t("discord") : t("slack")}
              </Text>
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
        </Flex>

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

        {connection.provider === "discord" &&
          connection.status === "reconnect_required" &&
          connection.last_health_code && (
            <Alert color="red" title={t("discordActivationFailureTitle")}>
              <Stack gap={2}>
                <Text size="sm">
                  {t(
                    `discordFailure.${discordFailureCode(connection.last_health_code)}.message`,
                  )}
                </Text>
                <Text size="sm" c="dimmed">
                  {t(
                    `discordFailure.${discordFailureCode(connection.last_health_code)}.action`,
                  )}
                </Text>
              </Stack>
            </Alert>
          )}

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

        <Stack gap={4}>
          <Switch
            label={t("openAccessEnabled")}
            description={t("openAccessEnabledDescription")}
            checked={connection.open_access_enabled}
            disabled={actionsBusy}
            onChange={(event) =>
              onUpdateAccessPolicy(connection, event.currentTarget.checked)
            }
          />
        </Stack>

        {connection.provider === "discord" &&
          connection.status !== "disconnected" && (
            <Stack gap="xs">
              <DiscordThreadAutoArchiveDurationSelect
                value={discordThreadDurationDraft}
                disabled={actionsBusy}
                onChange={onDiscordThreadDurationChange}
              />
              <Group justify="flex-end" gap="xs">
                {discordThreadDurationSaved &&
                  discordThreadDurationDraft ===
                    currentDiscordThreadDuration && (
                    <Text size="sm" c="teal">
                      {t("discordThreadAutoArchiveDurationSaved")}
                    </Text>
                  )}
                <Button
                  size="xs"
                  loading={busy}
                  disabled={
                    actionsBusy ||
                    discordThreadDurationDraft === currentDiscordThreadDuration
                  }
                  onClick={onSaveDiscordThreadDuration}
                >
                  {t("saveChanges")}
                </Button>
              </Group>
            </Stack>
          )}

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
            onClick={() => onDisconnect(connection)}
          >
            {t("disconnect")}
          </Button>
        </Group>
      </Stack>
    </Paper>
  );
}

function AssociatedMultiAppRow({
  connection,
}: {
  connection: ManagedMultiConnection;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");

  return (
    <Group
      justify="space-between"
      align="flex-start"
      wrap="wrap"
      py="sm"
      data-testid={`associated-multi-app-${connection.id}`}
    >
      <Box style={{ minWidth: 0 }}>
        <Group gap="xs">
          <Text fw={600} size="sm">
            {connection.provider_app_id ?? connection.id}
          </Text>
          <Badge color={statusColor(connection.status)} variant="light">
            {t(`status.${connection.status}`)}
          </Badge>
          <Badge color="gray" variant="outline">
            {t(`transport.${connection.transport}`)}
          </Badge>
        </Group>
        <Text size="xs" c="dimmed" mt={4}>
          {connection.provider_tenant_id ?? t("identityUnavailable")}
        </Text>
      </Box>
      <Group gap="xs">
        <Badge variant="light">
          {t("associatedAgentCount", {
            count: connection.active_agent_count,
          })}
        </Badge>
        <Badge variant="light" color="gray">
          {t("associatedDefaultCount", {
            count: connection.configured_default_count,
          })}
        </Badge>
      </Group>
    </Group>
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
        onClick={onRemove}
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
        {manifest.transport === "http" && manifest.callback_url && (
          <Alert color="yellow" title={t("existingAppInteractivityTitle")}>
            <Stack gap="xs">
              <Text size="sm">{t("existingAppInteractivityDescription")}</Text>
              <GuideCodeBlock>{manifest.callback_url}</GuideCodeBlock>
              <Group justify="flex-end">
                <CopyValueButton
                  value={manifest.callback_url}
                  label={t("copyCallback")}
                />
              </Group>
            </Stack>
          </Alert>
        )}
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
                {manifest.transport === "http" && (
                  <List.Item>{t("manualInteractivityStep")}</List.Item>
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

function DiscordConnectionDialog({
  state,
  actionError,
  saving,
  onChange,
  onClose,
  onSubmit,
}: {
  state: DiscordConnectionDialogState;
  actionError: string | null;
  saving: boolean;
  onChange: (state: Exclude<DiscordConnectionDialogState, null>) => void;
  onClose: () => void;
  onSubmit: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const disabled =
    state === null ||
    state.appId.trim() === "" ||
    state.targetGuildId.trim() === "" ||
    state.botToken.trim() === "";
  const guideCopy = {
    title: t("discordGuideTitle"),
    description: t("discordGuide"),
    createApplication: t("discordGuideCreateApplication"),
    enableIntent: t("discordGuideEnableIntent"),
    copyIdentifiers: t("discordGuideCopyIdentifiers"),
    configureOAuth: t("discordGuideConfigureOAuth"),
    grantBotPermissions: t("discordGuideGrantBotPermissions"),
    verifyChannelPermissions: t("discordGuideVerifyChannelPermissions"),
    finishSetup: t("discordGuideFinishSetup"),
    gatewayIntentLabel: t("discordGuideGatewayIntentLabel"),
    oauthScopesLabel: t("discordGuideOAuthScopesLabel"),
    botPermissionsLabel: t("discordGuideBotPermissionsLabel"),
    channelPermissionsLabel: t("discordGuideChannelPermissionsLabel"),
    leastPrivilegeNote: t("discordGuideLeastPrivilegeNote"),
  };

  return (
    <Modal
      opened={state !== null}
      onClose={() => {
        if (!saving) {
          onClose();
        }
      }}
      title={
        state?.type === "EDIT" ? t("discordEditTitle") : t("discordSetupTitle")
      }
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
          <DiscordSetupGuide copy={guideCopy} />
          <TextInput
            label={t("discordAppId")}
            value={state.appId}
            disabled={saving}
            onChange={(event) =>
              onChange({ ...state, appId: event.currentTarget.value })
            }
          />
          <TextInput
            label={t("discordGuildId")}
            value={state.targetGuildId}
            disabled={saving}
            onChange={(event) =>
              onChange({ ...state, targetGuildId: event.currentTarget.value })
            }
          />
          {state.type === "SETUP" && (
            <DiscordThreadAutoArchiveDurationSelect
              value={state.threadAutoArchiveDurationMinutes}
              disabled={saving}
              onChange={(threadAutoArchiveDurationMinutes) =>
                onChange({ ...state, threadAutoArchiveDurationMinutes })
              }
            />
          )}
          <PasswordInput
            label={t("discordBotToken")}
            value={state.botToken}
            disabled={saving}
            onChange={(event) =>
              onChange({ ...state, botToken: event.currentTarget.value })
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
  handle,
  state,
  manifestState,
  dialogState,
  discordDialogState,
  actionError,
  actionTarget,
  actionsBusy,
  discordThreadDurationDrafts,
  discordThreadDurationSavedConnectionId,
  defaultResponseMode,
  defaultResponseModeDraft,
  defaultResponseModeSaving,
  defaultResponseModeError,
  defaultResponseModeSaved,
  canManageWorkspaceMultiApps,
  onDefaultResponseModeChange,
  onSaveDefaultResponseMode,
  onOpenSetup,
  onOpenDiscordSetup,
  onOpenEdit,
  onCloseDialog,
  onDialogChange,
  onSubmitDialog,
  onCloseDiscordDialog,
  onDiscordDialogChange,
  onSubmitDiscordDialog,
  onValidate,
  onDisconnect,
  onUpdateAccessPolicy,
  onDiscordThreadDurationChange,
  onSaveDiscordThreadDuration,
  onRevokeGrant,
  onRemoveBlock,
}: ExternalChannelSettingsContainerOutput): React.ReactElement {
  const t = useTranslations("workspace.agents.externalChannels");
  const modals = useModals();
  const loaded = state.type === "LOADED" ? state : null;
  const openConfirm = ({
    title,
    description,
    confirmLabel,
    onConfirm,
  }: {
    title: string;
    description: string;
    confirmLabel: string;
    onConfirm: () => void;
  }): void => {
    modals.openConfirmModal({
      title,
      children: <Text size="sm">{description}</Text>,
      labels: { confirm: confirmLabel, cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm,
    });
  };

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
          <Group gap="xs">
            <Button
              variant="light"
              leftSection={<IconBrandSlack size={rem(16)} />}
              disabled={actionsBusy}
              onClick={onOpenSetup}
            >
              {t("setupTitle")}
            </Button>
            <Button
              variant="light"
              leftSection={<IconBrandDiscord size={rem(16)} />}
              disabled={actionsBusy}
              onClick={onOpenDiscordSetup}
            >
              {t("discordSetupTitle")}
            </Button>
          </Group>
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
            <Paper
              withBorder
              radius="lg"
              p="md"
              data-testid="external-default-response-mode"
            >
              <Stack gap="md">
                <Box>
                  <Text fw={700}>{t("defaultResponseModeTitle")}</Text>
                  <Text size="sm" c="dimmed">
                    {t("defaultResponseModeDescription")}
                  </Text>
                </Box>
                <Radio.Group
                  value={defaultResponseModeDraft}
                  onChange={(value) =>
                    onDefaultResponseModeChange(
                      value === "mention_only"
                        ? "mention_only"
                        : "all_messages",
                    )
                  }
                >
                  <Stack gap="sm">
                    <Radio
                      value="all_messages"
                      label={t("responseMode.all_messages.label")}
                      description={t("responseMode.all_messages.description")}
                      disabled={defaultResponseModeSaving}
                    />
                    <Radio
                      value="mention_only"
                      label={t("responseMode.mention_only.label")}
                      description={t("responseMode.mention_only.description")}
                      disabled={defaultResponseModeSaving}
                    />
                  </Stack>
                </Radio.Group>
                {defaultResponseModeError && (
                  <Alert color="red">{defaultResponseModeError}</Alert>
                )}
                {defaultResponseModeSaved &&
                  defaultResponseModeDraft === defaultResponseMode && (
                    <Text size="sm" c="teal">
                      {t("defaultResponseModeSaved")}
                    </Text>
                  )}
                <Group justify="flex-end">
                  <Button
                    size="xs"
                    loading={defaultResponseModeSaving}
                    data-testid="save-external-default-response-mode"
                    disabled={
                      defaultResponseModeSaving ||
                      defaultResponseModeDraft === defaultResponseMode
                    }
                    onClick={onSaveDefaultResponseMode}
                  >
                    {t("saveResponseMode")}
                  </Button>
                </Group>
              </Stack>
            </Paper>

            <Stack gap="sm">
              <Text fw={700}>{t("connectionsTitle")}</Text>
              {loaded.connections.length === 0 ? (
                <Paper withBorder radius="lg" p="xl">
                  <Stack align="center" gap="xs">
                    <Text fw={700}>{t("emptyConnectionsTitle")}</Text>
                    <Text size="sm" c="dimmed" ta="center">
                      {t("emptyConnectionsDescription")}
                    </Text>
                    <Button
                      leftSection={<IconBrandSlack size={rem(16)} />}
                      variant="light"
                      onClick={onOpenSetup}
                    >
                      {t("setupTitle")}
                    </Button>
                    <Button
                      leftSection={<IconBrandDiscord size={rem(16)} />}
                      variant="light"
                      onClick={onOpenDiscordSetup}
                    >
                      {t("discordSetupTitle")}
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
                    discordThreadDurationDraft={
                      discordThreadDurationDrafts[connection.id] ??
                      discordThreadAutoArchiveDurationFromConfiguration(
                        connection.provider_config,
                      )
                    }
                    discordThreadDurationSaved={
                      discordThreadDurationSavedConnectionId === connection.id
                    }
                    onValidate={onValidate}
                    onEdit={onOpenEdit}
                    onUpdateAccessPolicy={onUpdateAccessPolicy}
                    onDiscordThreadDurationChange={(duration) =>
                      onDiscordThreadDurationChange(connection.id, duration)
                    }
                    onSaveDiscordThreadDuration={() =>
                      onSaveDiscordThreadDuration(connection)
                    }
                    onDisconnect={(selected) =>
                      openConfirm({
                        title: t("disconnect"),
                        description: t("disconnectConfirm"),
                        confirmLabel: t("disconnect"),
                        onConfirm: () => onDisconnect(selected),
                      })
                    }
                  />
                ))
              )}
            </Stack>

            <Paper withBorder radius="lg" p="md">
              <Stack gap="sm">
                <Group justify="space-between" align="flex-start">
                  <Box>
                    <Text fw={700}>{t("associatedMultiAppsTitle")}</Text>
                    <Text size="sm" c="dimmed">
                      {t("associatedMultiAppsDescription")}
                    </Text>
                  </Box>
                  {canManageWorkspaceMultiApps && (
                    <Button
                      component={Link}
                      href={`/w/${handle}/integrations`}
                      variant="light"
                      size="xs"
                      leftSection={<IconSettings size={rem(14)} />}
                    >
                      {t("manageWorkspaceApps")}
                    </Button>
                  )}
                </Group>
                {loaded.associatedMultiApps.length === 0 ? (
                  <Text size="sm" c="dimmed">
                    {t("emptyAssociatedMultiApps")}
                  </Text>
                ) : (
                  loaded.associatedMultiApps.map((connection, index) => (
                    <Box key={connection.id}>
                      {index > 0 && <Divider />}
                      <AssociatedMultiAppRow connection={connection} />
                    </Box>
                  ))
                )}
              </Stack>
            </Paper>

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
                          onRemove={() =>
                            openConfirm({
                              title: t("revoke"),
                              description: t("revokeConfirm"),
                              confirmLabel: t("revoke"),
                              onConfirm: () => onRevokeGrant(grant),
                            })
                          }
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
                          onRemove={() =>
                            openConfirm({
                              title: t("unblock"),
                              description: t("unblockConfirm"),
                              confirmLabel: t("unblock"),
                              onConfirm: () => onRemoveBlock(block),
                            })
                          }
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
      <DiscordConnectionDialog
        state={discordDialogState}
        actionError={actionError}
        saving={actionTarget === "discord-dialog"}
        onChange={onDiscordDialogChange}
        onClose={onCloseDiscordDialog}
        onSubmit={onSubmitDiscordDialog}
      />
    </Box>
  );
}
