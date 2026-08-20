"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  List,
  Loader,
  Paper,
  PasswordInput,
  rem,
  ScrollArea,
  SegmentedControl,
  Select,
  SimpleGrid,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
  UnstyledButton,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconArrowRight,
  IconBrandDiscord,
  IconBrandSlack,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { DiscordSetupGuide } from "@/shared/components/DiscordSetupGuide";
import {
  discordThreadAutoArchiveDurationFromConfiguration,
  discordThreadAutoArchiveDurationFromSelectValue,
} from "@/shared/lib/discord-thread-auto-archive-duration";
import type { WorkspaceSlackAppsContainerOutput } from "../containers/useWorkspaceSlackAppsContainer";
import type {
  DiscordMultiConnectionDraft,
  MultiConnectionDraft,
} from "../types";
import type {
  DiscordThreadAutoArchiveDurationMinutes,
  ExternalChannelTransport,
  ManagedChannelDefaultMutation,
} from "@azents/public-client";
import type { ReactElement } from "react";

function statusColor(status: string): string {
  switch (status) {
    case "active":
      return "green";
    case "reconnect_required":
    case "degraded":
      return "yellow";
    case "disconnected":
      return "gray";
    default:
      return "blue";
  }
}

function formatDate(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleString();
}

function isTransport(value: string): value is ExternalChannelTransport {
  return value === "http" || value === "socket";
}

function isDraftComplete(draft: MultiConnectionDraft): boolean {
  return (
    draft.appId.trim() !== "" &&
    draft.credentials.botToken.trim() !== "" &&
    draft.credentials.signingSecret.trim() !== "" &&
    (draft.transport === "http" || draft.credentials.appToken.trim() !== "")
  );
}

function isDiscordDraftComplete(draft: DiscordMultiConnectionDraft): boolean {
  return (
    draft.appId.trim() !== "" &&
    draft.targetGuildId.trim() !== "" &&
    draft.botToken.trim() !== ""
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
}): ReactElement {
  const t = useTranslations("workspace.integrations");
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

function SlackMultiAppGuide(): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <Alert color="blue" title={t("slackGuideTitle")}>
      <List size="sm" spacing="xs">
        <List.Item>{t("slackGuideStep1")}</List.Item>
        <List.Item>{t("slackGuideStep2")}</List.Item>
        <List.Item>{t("slackGuideStep3")}</List.Item>
        <List.Item>{t("slackGuideStep4")}</List.Item>
      </List>
    </Alert>
  );
}

function DiscordMultiAppGuide(): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <DiscordSetupGuide
      copy={{
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
      }}
    />
  );
}

function CredentialFields({
  draft,
  onChange,
}: {
  draft: MultiConnectionDraft;
  onChange: (draft: MultiConnectionDraft) => void;
}): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <Stack gap="xs">
      <TextInput
        label={t("appId")}
        required
        value={draft.appId}
        onChange={(event) =>
          onChange({ ...draft, appId: event.currentTarget.value })
        }
      />
      <SegmentedControl
        value={draft.transport}
        data={[
          { label: t("transport.http"), value: "http" },
          { label: t("transport.socket"), value: "socket" },
        ]}
        onChange={(value) => {
          if (isTransport(value)) {
            onChange({ ...draft, transport: value });
          }
        }}
      />
      <PasswordInput
        label={t("botToken")}
        required
        value={draft.credentials.botToken}
        onChange={(event) =>
          onChange({
            ...draft,
            credentials: {
              ...draft.credentials,
              botToken: event.currentTarget.value,
            },
          })
        }
      />
      <PasswordInput
        label={t("signingSecret")}
        required
        value={draft.credentials.signingSecret}
        onChange={(event) =>
          onChange({
            ...draft,
            credentials: {
              ...draft.credentials,
              signingSecret: event.currentTarget.value,
            },
          })
        }
      />
      <PasswordInput
        label={t("appToken")}
        required={draft.transport === "socket"}
        value={draft.credentials.appToken}
        description={
          draft.transport === "socket"
            ? t("appTokenRequired")
            : t("appTokenOptional")
        }
        onChange={(event) =>
          onChange({
            ...draft,
            credentials: {
              ...draft.credentials,
              appToken: event.currentTarget.value,
            },
          })
        }
      />
      <Text size="xs" c="dimmed">
        {t("credentialSafety")}
      </Text>
    </Stack>
  );
}

function DiscordCredentialFields({
  draft,
  onChange,
  showThreadDuration,
}: {
  draft: DiscordMultiConnectionDraft;
  onChange: (draft: DiscordMultiConnectionDraft) => void;
  showThreadDuration: boolean;
}): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <Stack gap="xs">
      <TextInput
        label={t("discordAppId")}
        required
        value={draft.appId}
        onChange={(event) =>
          onChange({ ...draft, appId: event.currentTarget.value })
        }
      />
      <TextInput
        label={t("discordGuildId")}
        required
        value={draft.targetGuildId}
        onChange={(event) =>
          onChange({ ...draft, targetGuildId: event.currentTarget.value })
        }
      />
      {showThreadDuration && (
        <DiscordThreadAutoArchiveDurationSelect
          value={draft.threadAutoArchiveDurationMinutes}
          disabled={false}
          onChange={(threadAutoArchiveDurationMinutes) =>
            onChange({ ...draft, threadAutoArchiveDurationMinutes })
          }
        />
      )}
      <PasswordInput
        label={t("discordBotToken")}
        required
        value={draft.botToken}
        onChange={(event) =>
          onChange({ ...draft, botToken: event.currentTarget.value })
        }
      />
      <Text size="xs" c="dimmed">
        {t("credentialSafety")}
      </Text>
    </Stack>
  );
}

function Pagination({
  offset,
  count,
  onChange,
}: {
  offset: number;
  count: number;
  onChange: (offset: number) => void;
}): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <Group justify="flex-end" gap="xs">
      <Button
        variant="subtle"
        size="xs"
        leftSection={<IconArrowLeft size={14} />}
        disabled={offset === 0}
        onClick={() => onChange(Math.max(0, offset - 50))}
      >
        {t("previous")}
      </Button>
      <Text size="xs" c="dimmed">
        {count === 0
          ? t("emptyPage")
          : t("pageRange", { start: offset + 1, end: offset + count })}
      </Text>
      <Button
        variant="subtle"
        size="xs"
        rightSection={<IconArrowRight size={14} />}
        disabled={count < 50}
        onClick={() => onChange(offset + 50)}
      >
        {t("next")}
      </Button>
    </Group>
  );
}

function DefaultMutationAlert({
  mutation,
}: {
  mutation: ManagedChannelDefaultMutation;
}): ReactElement {
  const t = useTranslations("workspace.integrations");

  return (
    <Alert
      color={mutation.changed ? "green" : "blue"}
      title={t(
        mutation.changed
          ? "defaultMutationChangedTitle"
          : "defaultMutationUnchangedTitle",
      )}
      data-testid="channel-default-mutation-impact"
    >
      {t("defaultMutationImpact", {
        settings: mutation.invalidated_participation_setting_count,
        claims: mutation.terminated_setup_claim_count,
        interactions: mutation.expired_interaction_count,
        bindings: mutation.disconnected_parent_binding_count,
        cleanups: mutation.direct_cleanup_count,
      })}
    </Alert>
  );
}

function FocusedHandoff({
  props,
}: {
  props: WorkspaceSlackAppsContainerOutput;
}): ReactElement {
  const t = useTranslations("workspace.integrations");
  const handoff = props.handoffState.handoff;

  if (props.state.type === "LOADING") {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  if (props.state.type === "FORBIDDEN") {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="yellow" title={t("handoffPermissionTitle")}>
          {t("handoffPermissionDescription")}
        </Alert>
      </Stack>
    );
  }

  if (props.state.type === "UNAVAILABLE" || props.state.type === "ERROR") {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="red" title={t("handoffUnavailableTitle")}>
          {props.state.message}
        </Alert>
      </Stack>
    );
  }

  if (!props.canManage) {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="yellow" title={t("handoffPermissionTitle")}>
          {t("handoffPermissionDescription")}
        </Alert>
      </Stack>
    );
  }

  if (props.handoffState.message) {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="red" title={t("handoffUnavailableTitle")}>
          {props.handoffState.message}
        </Alert>
      </Stack>
    );
  }

  if (props.detailError) {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="red" title={t("detailErrorTitle")}>
          {props.detailError}
        </Alert>
      </Stack>
    );
  }

  if (
    handoff === null ||
    props.selectedConnection === null ||
    props.connectionLoading ||
    props.routesLoading ||
    props.defaultsLoading
  ) {
    return (
      <Center py="xl">
        <Loader />
      </Center>
    );
  }

  const currentDefault = props.defaultItems.find(
    (item) =>
      item.provider_channel_id === handoff.provider_channel_id &&
      item.status === "active",
  );
  const routeOptions = props.routeItems
    .filter((route) => route.catalog_status === "available")
    .map((route) => ({
      value: route.id,
      label: route.agent_name ?? route.agent_id_snapshot,
    }));
  const canEditDefault = props.selectedConnection.status !== "disconnected";

  return (
    <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
      <Box>
        <Title order={2}>{t("handoffTitle")}</Title>
        <Text c="dimmed" size="sm">
          {t("handoffDescription", {
            channel: handoff.provider_channel_id,
            expiresAt: formatDate(handoff.expires_at),
          })}
        </Text>
      </Box>
      <Paper withBorder p="md" radius="md">
        <Stack gap="md">
          <Group justify="space-between">
            <Box>
              <Text fw={700}>
                {props.selectedConnection.provider_app_id ??
                  props.selectedConnection.id}
              </Text>
              <Text size="sm" c="dimmed">
                {props.selectedConnection.provider_tenant_id ??
                  t("identityUnavailable")}
              </Text>
            </Box>
            <Badge
              color={statusColor(props.selectedConnection.status)}
              variant="light"
            >
              {t(`statusValue.${props.selectedConnection.status}`)}
            </Badge>
          </Group>
          <TextInput
            label={t("channelId")}
            value={handoff.provider_channel_id}
            readOnly
          />
          <Text fw={600}>{t("currentDefault")}</Text>
          <Text c="dimmed" size="sm">
            {currentDefault?.agent_name ??
              currentDefault?.route_id ??
              t("defaultNotReturned")}
          </Text>
          <Select
            label={t("route")}
            placeholder={t("selectRoute")}
            data={routeOptions}
            value={props.defaultRouteId}
            disabled={!canEditDefault}
            onChange={(value) => props.onDefaultRouteIdChange(value ?? "")}
          />
          {(props.routeItems.length > 0 || props.routeOffset > 0) && (
            <Pagination
              offset={props.routeOffset}
              count={props.routeItems.length}
              onChange={props.onRoutePage}
            />
          )}
          <Group justify="flex-end">
            <Button
              color="red"
              variant="default"
              loading={props.busy}
              disabled={!canEditDefault}
              onClick={() => props.onClearDefault(handoff.provider_channel_id)}
            >
              {t("clear")}
            </Button>
            <Button
              loading={props.busy}
              disabled={!canEditDefault || props.defaultRouteId === ""}
              onClick={props.onSetDefault}
            >
              {t("setDefault")}
            </Button>
          </Group>
          {props.defaultMutation && (
            <DefaultMutationAlert mutation={props.defaultMutation} />
          )}
        </Stack>
      </Paper>
    </Stack>
  );
}

export function WorkspaceSlackApps(
  props: WorkspaceSlackAppsContainerOutput,
): ReactElement {
  const t = useTranslations("workspace.integrations");

  if (props.focusedHandoff) {
    return <FocusedHandoff props={props} />;
  }

  switch (props.state.type) {
    case "LOADING":
      return (
        <Center py="xl">
          <Loader />
        </Center>
      );
    case "FORBIDDEN":
      return (
        <Alert color="yellow" title={t("forbiddenTitle")}>
          {t("forbiddenDescription")}
        </Alert>
      );
    case "UNAVAILABLE":
      return (
        <Alert color="orange" title={t("unavailableTitle")}>
          {props.state.message}
        </Alert>
      );
    case "ERROR":
      return (
        <Alert color="red" title={t("errorTitle")}>
          {props.state.message}
        </Alert>
      );
    case "LOADED":
      break;
  }

  const routeOptions = props.routeItems
    .filter((route) => route.catalog_status === "available")
    .map((route) => ({
      value: route.id,
      label: route.agent_name ?? route.agent_id_snapshot,
    }));
  const selectedConnectionIsDisconnected =
    props.selectedConnection?.status === "disconnected";

  return (
    <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(1320)} mx="auto">
      <Group justify="space-between" align="flex-start">
        <Box>
          <Title order={2}>{t("title")}</Title>
          <Text c="dimmed" size="sm">
            {t("description")}
          </Text>
        </Box>
        <Badge variant="light">
          {t("appCount", { count: props.state.connections.length })}
        </Badge>
      </Group>
      {props.actionError && (
        <Alert color="red" title={t("actionFailed")}>
          {props.actionError}
        </Alert>
      )}
      {props.detailError && (
        <Alert color="red" title={t("detailErrorTitle")}>
          {props.detailError}
        </Alert>
      )}
      {props.handoffState.message && (
        <Alert color="red">{props.handoffState.message}</Alert>
      )}

      {props.canManage && (
        <SimpleGrid cols={{ base: 1, md: 2 }} spacing="md">
          <Paper withBorder p="md" radius="md">
            <Stack gap="sm">
              <Text fw={700}>{t("createTitle")}</Text>
              <SlackMultiAppGuide />
              <CredentialFields
                draft={props.setupDraft}
                onChange={props.onSetupDraftChange}
              />
              <Group justify="flex-end">
                <Button
                  leftSection={<IconBrandSlack size={16} />}
                  loading={props.busy}
                  disabled={!isDraftComplete(props.setupDraft)}
                  onClick={props.onCreate}
                >
                  {t("create")}
                </Button>
              </Group>
            </Stack>
          </Paper>
          <Paper withBorder p="md" radius="md">
            <Stack gap="sm">
              <Text fw={700}>{t("discordCreateTitle")}</Text>
              <DiscordMultiAppGuide />
              <DiscordCredentialFields
                draft={props.discordSetupDraft}
                onChange={props.onDiscordSetupDraftChange}
                showThreadDuration
              />
              <Group justify="flex-end">
                <Button
                  leftSection={<IconBrandDiscord size={16} />}
                  loading={props.busy}
                  disabled={!isDiscordDraftComplete(props.discordSetupDraft)}
                  onClick={props.onCreateDiscord}
                >
                  {t("discordCreate")}
                </Button>
              </Group>
            </Stack>
          </Paper>
        </SimpleGrid>
      )}

      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>{t("appsTitle")}</Text>
            <Text size="xs" c="dimmed">
              {t("historyVisible")}
            </Text>
          </Group>
          {props.state.connections.length === 0 &&
          props.connectionOffset === 0 ? (
            <Text c="dimmed">{t("empty")}</Text>
          ) : (
            <>
              <ScrollArea type="auto">
                <Table
                  striped
                  highlightOnHover
                  miw={rem(980)}
                  verticalSpacing="sm"
                >
                  <Table.Thead>
                    <Table.Tr>
                      <Table.Th>{t("app")}</Table.Th>
                      <Table.Th>{t("status")}</Table.Th>
                      <Table.Th>{t("agents")}</Table.Th>
                      <Table.Th>{t("defaults")}</Table.Th>
                      <Table.Th>{t("transportLabel")}</Table.Th>
                      <Table.Th>{t("lastHealth")}</Table.Th>
                    </Table.Tr>
                  </Table.Thead>
                  <Table.Tbody>
                    {props.state.connections.map((connection) => (
                      <Table.Tr
                        key={connection.id}
                        {...(props.selectedConnectionId === connection.id
                          ? { bg: "var(--mantine-color-blue-light)" }
                          : {})}
                      >
                        <Table.Td>
                          <UnstyledButton
                            w="100%"
                            ta="left"
                            aria-pressed={
                              props.selectedConnectionId === connection.id
                            }
                            onClick={() => props.onSelectConnection(connection)}
                          >
                            <Text fw={600}>
                              {connection.provider_app_id ?? connection.id}
                            </Text>
                            <Text size="xs" c="dimmed">
                              {connection.provider_tenant_id ??
                                t("identityUnavailable")}
                            </Text>
                          </UnstyledButton>
                        </Table.Td>
                        <Table.Td>
                          <Badge
                            color={statusColor(connection.status)}
                            variant="light"
                          >
                            {t(`statusValue.${connection.status}`)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Badge
                            color={
                              connection.active_agent_count === 0
                                ? "yellow"
                                : "blue"
                            }
                            variant="light"
                          >
                            {t("agentCount", {
                              count: connection.active_agent_count,
                            })}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          <Badge color="gray" variant="light">
                            {t("defaultCount", {
                              count: connection.configured_default_count,
                            })}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          {t(`transport.${connection.transport}`)}
                        </Table.Td>
                        <Table.Td>
                          {formatDate(connection.last_health_at)}
                        </Table.Td>
                      </Table.Tr>
                    ))}
                  </Table.Tbody>
                </Table>
              </ScrollArea>
              <Pagination
                offset={props.connectionOffset}
                count={props.state.connections.length}
                onChange={props.onConnectionPage}
              />
            </>
          )}
        </Stack>
      </Paper>

      {props.selectedConnectionId &&
        props.selectedConnection === null &&
        props.connectionLoading && (
          <Paper withBorder radius="md" p="xl">
            <Center>
              <Loader size="sm" />
            </Center>
          </Paper>
        )}

      {props.selectedConnection?.id === props.selectedConnectionId && (
        <Paper withBorder radius="md" p="md">
          <Stack gap="lg">
            <Group justify="space-between" align="flex-start">
              <Box>
                <Text fw={700}>
                  {props.selectedConnection.provider_app_id ??
                    props.selectedConnection.id}
                </Text>
                <Text size="sm" c="dimmed">
                  {props.selectedConnection.provider_tenant_id ??
                    t("identityUnavailable")}
                </Text>
              </Box>
              <Group gap="xs" justify="flex-end">
                <Badge variant="light">
                  {t("agentCount", {
                    count: props.selectedConnection.active_agent_count,
                  })}
                </Badge>
                <Badge color="gray" variant="light">
                  {t("defaultCount", {
                    count: props.selectedConnection.configured_default_count,
                  })}
                </Badge>
                <Badge color={statusColor(props.selectedConnection.status)}>
                  {t(`statusValue.${props.selectedConnection.status}`)}
                </Badge>
              </Group>
            </Group>
            {!props.selectedConnection.credentials_configured && (
              <Alert color="yellow" title={t("credentialsMissingTitle")}>
                {t("credentialsMissingDescription")}
              </Alert>
            )}
            {props.selectedConnection.status === "reconnect_required" && (
              <Alert color="yellow" title={t("reconnectTitle")}>
                {t("reconnectDescription")}
              </Alert>
            )}
            {props.selectedConnection.status === "disconnected" && (
              <Alert color="gray" title={t("disconnectedTitle")}>
                {t("disconnectedDescription")}
              </Alert>
            )}
            {props.selectedConnection.active_agent_count === 0 &&
              props.selectedConnection.status !== "disconnected" && (
                <Alert color="blue" title={t("noAgentsTitle")}>
                  {t("noAgentsDescription")}
                </Alert>
              )}
            {props.canManage &&
              !selectedConnectionIsDisconnected &&
              props.selectedConnection.provider === "discord" && (
                <>
                  <DiscordThreadAutoArchiveDurationSelect
                    value={props.discordThreadDurationDraft}
                    disabled={props.busy}
                    onChange={props.onDiscordThreadDurationChange}
                  />
                  <Group justify="flex-end" gap="xs">
                    {props.discordThreadDurationSaved &&
                      props.discordThreadDurationDraft ===
                        discordThreadAutoArchiveDurationFromConfiguration(
                          props.selectedConnection.provider_config,
                        ) && (
                        <Text size="sm" c="teal">
                          {t("discordThreadAutoArchiveDurationSaved")}
                        </Text>
                      )}
                    <Button
                      size="xs"
                      loading={props.busy}
                      disabled={
                        props.busy ||
                        props.discordThreadDurationDraft ===
                          discordThreadAutoArchiveDurationFromConfiguration(
                            props.selectedConnection.provider_config,
                          )
                      }
                      onClick={props.onSaveDiscordThreadDuration}
                    >
                      {t("save")}
                    </Button>
                  </Group>
                  <Divider />
                </>
              )}
            {props.canManage && !selectedConnectionIsDisconnected && (
              <>
                <Text size="sm" c="dimmed">
                  {props.selectedConnection.provider === "discord"
                    ? t("discordReplaceCredentials")
                    : t("replaceCredentials")}
                </Text>
                {props.selectedConnection.provider === "discord" ? (
                  <DiscordCredentialFields
                    draft={props.discordEditDraft}
                    onChange={props.onDiscordEditDraftChange}
                    showThreadDuration={false}
                  />
                ) : (
                  <CredentialFields
                    draft={props.editDraft}
                    onChange={props.onEditDraftChange}
                  />
                )}
                <Group justify="flex-end">
                  <Button
                    variant="default"
                    leftSection={<IconRefresh size={16} />}
                    loading={props.busy}
                    onClick={props.onValidate}
                  >
                    {t("validate")}
                  </Button>
                  <Button
                    loading={props.busy}
                    disabled={
                      props.selectedConnection.provider === "discord"
                        ? !isDiscordDraftComplete(props.discordEditDraft)
                        : !isDraftComplete(props.editDraft)
                    }
                    onClick={
                      props.selectedConnection.provider === "discord"
                        ? props.onSaveDiscordConnection
                        : props.onSaveConnection
                    }
                  >
                    {t("save")}
                  </Button>
                </Group>
              </>
            )}

            <Divider />
            <Stack gap="sm">
              <Text fw={700}>{t("catalogTitle")}</Text>
              {props.canManage && !selectedConnectionIsDisconnected && (
                <Group align="end">
                  <TextInput
                    flex={1}
                    label={t("agentId")}
                    value={props.agentId}
                    onChange={(event) =>
                      props.onAgentIdChange(event.currentTarget.value)
                    }
                  />
                  <Button
                    loading={props.busy}
                    disabled={props.agentId.trim() === ""}
                    onClick={props.onAddRoute}
                  >
                    {t("addAgent")}
                  </Button>
                </Group>
              )}
              {props.routesLoading ? (
                <Center py="md">
                  <Loader size="sm" />
                </Center>
              ) : props.routeItems.length === 0 && props.routeOffset === 0 ? (
                <Text size="sm" c="dimmed">
                  {t("emptyCatalog")}
                </Text>
              ) : (
                <>
                  <ScrollArea type="auto">
                    <Table miw={rem(680)}>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>{t("agent")}</Table.Th>
                          <Table.Th>{t("routeStatus")}</Table.Th>
                          <Table.Th>{t("actions")}</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {props.routeItems.map((route) => (
                          <Table.Tr key={route.id}>
                            <Table.Td>
                              <Text fw={600}>
                                {route.agent_name ?? route.agent_id_snapshot}
                              </Text>
                              <Text size="xs" c="dimmed">
                                {route.id}
                              </Text>
                            </Table.Td>
                            <Table.Td>
                              <Badge
                                color={
                                  route.catalog_status === "available"
                                    ? "green"
                                    : "gray"
                                }
                              >
                                {t(`routeStatusValue.${route.catalog_status}`)}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              {props.canManage &&
                                !selectedConnectionIsDisconnected &&
                                (route.catalog_status === "removed" ? (
                                  <Button
                                    size="xs"
                                    variant="subtle"
                                    loading={props.busy}
                                    onClick={() =>
                                      props.onReenableRoute(route.id)
                                    }
                                  >
                                    {t("reenable")}
                                  </Button>
                                ) : (
                                  <Button
                                    size="xs"
                                    color="red"
                                    variant="subtle"
                                    loading={props.busy}
                                    onClick={() =>
                                      props.onPreviewRouteRemoval(route.id)
                                    }
                                  >
                                    {t("remove")}
                                  </Button>
                                ))}
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                  <Pagination
                    offset={props.routeOffset}
                    count={props.routeItems.length}
                    onChange={props.onRoutePage}
                  />
                </>
              )}
              {props.previewRouteId && (
                <Alert
                  color="orange"
                  icon={<IconAlertTriangle size={16} />}
                  title={t("routeImpactTitle")}
                >
                  {props.routeImpactError
                    ? props.routeImpactError
                    : props.routeImpact
                      ? t("routeImpactDescription", {
                          defaults: props.routeImpact.active_default_count,
                          settings:
                            props.routeImpact
                              .active_participation_setting_count,
                          claims:
                            props.routeImpact.nonterminal_setup_claim_count,
                          bindings: props.routeImpact.active_binding_count,
                          parentBindings:
                            props.routeImpact.connected_parent_binding_count,
                          admissions: props.routeImpact.open_admission_count,
                        })
                      : t("loadingImpact")}
                  <Group mt="sm">
                    <Button
                      size="xs"
                      color="red"
                      loading={props.busy || props.routeImpactLoading}
                      disabled={
                        props.routeImpact === null ||
                        props.routeImpactError !== null
                      }
                      onClick={props.onRemoveRoute}
                    >
                      {t("confirmRemove")}
                    </Button>
                    {props.routeImpactError && (
                      <Button
                        size="xs"
                        variant="light"
                        onClick={props.onRetryRouteImpact}
                      >
                        {t("retry")}
                      </Button>
                    )}
                    <Button
                      size="xs"
                      variant="default"
                      onClick={props.onCancelPreview}
                    >
                      {t("cancel")}
                    </Button>
                  </Group>
                </Alert>
              )}
            </Stack>

            <Divider />
            <Stack gap="sm">
              <Text fw={700}>{t("defaultsTitle")}</Text>
              {props.defaultMutation && (
                <DefaultMutationAlert mutation={props.defaultMutation} />
              )}
              {props.canManage && !selectedConnectionIsDisconnected && (
                <Group align="end" grow>
                  <TextInput
                    label={t("channelId")}
                    value={props.providerChannelId}
                    onChange={(event) =>
                      props.onProviderChannelIdChange(event.currentTarget.value)
                    }
                  />
                  <Select
                    label={t("route")}
                    placeholder={t("selectRoute")}
                    data={routeOptions}
                    value={props.defaultRouteId}
                    onChange={(value) =>
                      props.onDefaultRouteIdChange(value ?? "")
                    }
                  />
                  <Button
                    loading={props.busy}
                    disabled={
                      props.providerChannelId.trim() === "" ||
                      props.defaultRouteId === ""
                    }
                    onClick={props.onSetDefault}
                  >
                    {t("setDefault")}
                  </Button>
                </Group>
              )}
              {props.defaultsLoading ? (
                <Center py="md">
                  <Loader size="sm" />
                </Center>
              ) : props.defaultItems.length === 0 &&
                props.defaultOffset === 0 ? (
                <Text size="sm" c="dimmed">
                  {t("emptyDefaults")}
                </Text>
              ) : (
                <>
                  <ScrollArea type="auto">
                    <Table miw={rem(680)}>
                      <Table.Thead>
                        <Table.Tr>
                          <Table.Th>{t("channel")}</Table.Th>
                          <Table.Th>{t("defaultAgent")}</Table.Th>
                          <Table.Th>{t("defaultStatus")}</Table.Th>
                          <Table.Th>{t("actions")}</Table.Th>
                        </Table.Tr>
                      </Table.Thead>
                      <Table.Tbody>
                        {props.defaultItems.map((item) => (
                          <Table.Tr key={item.id}>
                            <Table.Td>{item.provider_channel_id}</Table.Td>
                            <Table.Td>
                              {item.agent_name ?? item.route_id}
                            </Table.Td>
                            <Table.Td>
                              <Badge
                                color={
                                  item.status === "active" ? "green" : "gray"
                                }
                              >
                                {t(`defaultStatusValue.${item.status}`)}
                              </Badge>
                            </Table.Td>
                            <Table.Td>
                              {props.canManage &&
                                !selectedConnectionIsDisconnected &&
                                item.status === "active" && (
                                  <Button
                                    size="xs"
                                    color="red"
                                    variant="subtle"
                                    loading={props.busy}
                                    onClick={() =>
                                      props.onClearDefault(
                                        item.provider_channel_id,
                                      )
                                    }
                                  >
                                    {t("clear")}
                                  </Button>
                                )}
                            </Table.Td>
                          </Table.Tr>
                        ))}
                      </Table.Tbody>
                    </Table>
                  </ScrollArea>
                  <Pagination
                    offset={props.defaultOffset}
                    count={props.defaultItems.length}
                    onChange={props.onDefaultPage}
                  />
                </>
              )}
            </Stack>

            {props.canManage && !selectedConnectionIsDisconnected && (
              <>
                <Divider />
                <Group justify="space-between">
                  <Box>
                    <Text fw={700} c="red">
                      {t("disconnectTitle")}
                    </Text>
                    <Text size="sm" c="dimmed">
                      {t("disconnectDescription")}
                    </Text>
                  </Box>
                  <Button
                    color="red"
                    variant="light"
                    leftSection={<IconTrash size={16} />}
                    onClick={props.onPreviewDisconnect}
                  >
                    {t("disconnect")}
                  </Button>
                </Group>
                {props.previewDisconnect && (
                  <Alert color="red" title={t("connectionImpactTitle")}>
                    {props.connectionImpactError
                      ? props.connectionImpactError
                      : props.connectionImpact
                        ? t("connectionImpactDescription", {
                            routes: props.connectionImpact.active_route_count,
                            defaults:
                              props.connectionImpact.active_default_count,
                            settings:
                              props.connectionImpact
                                .active_participation_setting_count,
                            claims:
                              props.connectionImpact
                                .nonterminal_setup_claim_count,
                            bindings:
                              props.connectionImpact.active_binding_count,
                            parentBindings:
                              props.connectionImpact
                                .connected_parent_binding_count,
                          })
                        : t("loadingImpact")}
                    <Group mt="sm">
                      <Button
                        size="xs"
                        color="red"
                        loading={props.busy || props.connectionImpactLoading}
                        disabled={
                          props.connectionImpact === null ||
                          props.connectionImpactError !== null
                        }
                        onClick={props.onDisconnect}
                      >
                        {t("confirmDisconnect")}
                      </Button>
                      {props.connectionImpactError && (
                        <Button
                          size="xs"
                          variant="light"
                          onClick={props.onRetryConnectionImpact}
                        >
                          {t("retry")}
                        </Button>
                      )}
                      <Button
                        size="xs"
                        variant="default"
                        onClick={props.onCancelPreview}
                      >
                        {t("cancel")}
                      </Button>
                    </Group>
                  </Alert>
                )}
              </>
            )}
          </Stack>
        </Paper>
      )}
    </Stack>
  );
}
