"use client";

import {
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Paper,
  PasswordInput,
  rem,
  ScrollArea,
  SegmentedControl,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import {
  IconAlertTriangle,
  IconArrowLeft,
  IconArrowRight,
  IconPlugConnected,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { WorkspaceSlackAppsContainerOutput } from "../containers/useWorkspaceSlackAppsContainer";
import type { MultiConnectionDraft } from "../types";
import type { ExternalChannelTransport } from "@azents/public-client";
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

function CredentialFields({
  draft,
  onChange,
}: {
  draft: MultiConnectionDraft;
  onChange: (draft: MultiConnectionDraft) => void;
}): ReactElement {
  const t = useTranslations("workspace.slackApps");

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

function Pagination({
  offset,
  count,
  onChange,
}: {
  offset: number;
  count: number;
  onChange: (offset: number) => void;
}): ReactElement {
  const t = useTranslations("workspace.slackApps");

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
        {t("pageRange", { start: offset + 1, end: offset + count })}
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

function FocusedHandoff({
  props,
}: {
  props: WorkspaceSlackAppsContainerOutput;
}): ReactElement {
  const t = useTranslations("workspace.slackApps");
  const handoff = props.handoffState.handoff;

  if (props.handoffState.message) {
    return (
      <Stack gap="lg" p={{ base: "md", sm: "xl" }} maw={rem(820)} mx="auto">
        <Alert color="red" title={t("handoffUnavailableTitle")}>
          {props.handoffState.message}
        </Alert>
      </Stack>
    );
  }

  if (props.state.type === "FORBIDDEN" || !props.canManage) {
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

  if (
    props.state.type === "LOADING" ||
    handoff === null ||
    props.selectedConnection === null
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
            onChange={(value) => props.onDefaultRouteIdChange(value ?? "")}
          />
          <Group justify="flex-end">
            <Button
              color="red"
              variant="default"
              loading={props.busy}
              disabled={!props.canManage}
              onClick={() => props.onClearDefault(handoff.provider_channel_id)}
            >
              {t("clear")}
            </Button>
            <Button
              loading={props.busy}
              disabled={props.defaultRouteId === ""}
              onClick={props.onSetDefault}
            >
              {t("setDefault")}
            </Button>
          </Group>
        </Stack>
      </Paper>
    </Stack>
  );
}

export function WorkspaceSlackApps(
  props: WorkspaceSlackAppsContainerOutput,
): ReactElement {
  const t = useTranslations("workspace.slackApps");

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
      {props.handoffState.message && (
        <Alert color="red">{props.handoffState.message}</Alert>
      )}

      {props.canManage && (
        <Paper withBorder p="md" radius="md">
          <Stack gap="sm">
            <Text fw={700}>{t("createTitle")}</Text>
            <CredentialFields
              draft={props.setupDraft}
              onChange={props.onSetupDraftChange}
            />
            <Group justify="flex-end">
              <Button
                leftSection={<IconPlugConnected size={16} />}
                loading={props.busy}
                disabled={!isDraftComplete(props.setupDraft)}
                onClick={props.onCreate}
              >
                {t("create")}
              </Button>
            </Group>
          </Stack>
        </Paper>
      )}

      <Paper withBorder radius="md" p="md">
        <Stack gap="sm">
          <Group justify="space-between">
            <Text fw={700}>{t("appsTitle")}</Text>
            <Text size="xs" c="dimmed">
              {t("historyVisible")}
            </Text>
          </Group>
          {props.state.connections.length === 0 ? (
            <Text c="dimmed">{t("empty")}</Text>
          ) : (
            <ScrollArea type="auto">
              <Table
                striped
                highlightOnHover
                miw={rem(720)}
                verticalSpacing="sm"
              >
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t("app")}</Table.Th>
                    <Table.Th>{t("status")}</Table.Th>
                    <Table.Th>{t("transportLabel")}</Table.Th>
                    <Table.Th>{t("lastHealth")}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {props.state.connections.map((connection) => (
                    <Table.Tr
                      key={connection.id}
                      style={{ cursor: "pointer" }}
                      {...(props.selectedConnectionId === connection.id
                        ? { bg: "var(--mantine-color-blue-light)" }
                        : {})}
                      onClick={() => props.onSelectConnection(connection.id)}
                    >
                      <Table.Td>
                        <Text fw={600}>
                          {connection.provider_app_id ?? connection.id}
                        </Text>
                        <Text size="xs" c="dimmed">
                          {connection.provider_tenant_id ??
                            t("identityUnavailable")}
                        </Text>
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
          )}
        </Stack>
      </Paper>

      {props.selectedConnection && (
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
              <Badge color={statusColor(props.selectedConnection.status)}>
                {t(`statusValue.${props.selectedConnection.status}`)}
              </Badge>
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
            {props.canManage &&
              props.selectedConnection.status !== "disconnected" && (
                <>
                  <Text size="sm" c="dimmed">
                    {t("replaceCredentials")}
                  </Text>
                  <CredentialFields
                    draft={props.editDraft}
                    onChange={props.onEditDraftChange}
                  />
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
                      disabled={!isDraftComplete(props.editDraft)}
                      onClick={props.onSaveConnection}
                    >
                      {t("save")}
                    </Button>
                  </Group>
                </>
              )}

            <Divider />
            <Stack gap="sm">
              <Text fw={700}>{t("catalogTitle")}</Text>
              {props.canManage && (
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
                            (route.catalog_status === "removed" ? (
                              <Button
                                size="xs"
                                variant="subtle"
                                loading={props.busy}
                                onClick={() => props.onReenableRoute(route.id)}
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
              {props.previewRouteId && (
                <Alert
                  color="orange"
                  icon={<IconAlertTriangle size={16} />}
                  title={t("routeImpactTitle")}
                >
                  {props.routeImpact
                    ? t("routeImpactDescription", {
                        defaults: props.routeImpact.active_default_count,
                        bindings: props.routeImpact.active_binding_count,
                        admissions: props.routeImpact.open_admission_count,
                      })
                    : t("loadingImpact")}
                  <Group mt="sm">
                    <Button
                      size="xs"
                      color="red"
                      loading={props.busy || !props.routeImpact}
                      onClick={props.onRemoveRoute}
                    >
                      {t("confirmRemove")}
                    </Button>
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
              {props.canManage && (
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
                        <Table.Td>{item.agent_name ?? item.route_id}</Table.Td>
                        <Table.Td>
                          <Badge
                            color={item.status === "active" ? "green" : "gray"}
                          >
                            {t(`defaultStatusValue.${item.status}`)}
                          </Badge>
                        </Table.Td>
                        <Table.Td>
                          {props.canManage && item.status === "active" && (
                            <Button
                              size="xs"
                              color="red"
                              variant="subtle"
                              loading={props.busy}
                              onClick={() =>
                                props.onClearDefault(item.provider_channel_id)
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
            </Stack>

            {props.canManage &&
              props.selectedConnection.status !== "disconnected" && (
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
                      {props.connectionImpact
                        ? t("connectionImpactDescription", {
                            routes: props.connectionImpact.active_route_count,
                            defaults:
                              props.connectionImpact.active_default_count,
                            bindings:
                              props.connectionImpact.active_binding_count,
                          })
                        : t("loadingImpact")}
                      <Group mt="sm">
                        <Button
                          size="xs"
                          color="red"
                          loading={props.busy || !props.connectionImpact}
                          onClick={props.onDisconnect}
                        >
                          {t("confirmDisconnect")}
                        </Button>
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
