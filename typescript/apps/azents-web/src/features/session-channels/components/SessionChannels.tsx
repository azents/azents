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
  rem,
  SimpleGrid,
  Stack,
  Text,
} from "@mantine/core";
import { useModals } from "@mantine/modals";
import {
  IconArchive,
  IconCheck,
  IconClock,
  IconLoader2,
  IconPlugConnectedX,
  IconShieldCheck,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import type { SessionChannelsContainerOutput } from "../containers/useSessionChannelsContainer";
import type {
  ExternalChannelDeliveryStatus,
  ManagedBinding,
  ManagedDelivery,
  ManagedGrant,
  ManagedWork,
} from "@azents/public-client";

type WorkTaskStatus = "pending" | "in_progress" | "completed";

interface WorkTask {
  title: string;
  status: WorkTaskStatus;
}

function formatDate(value: string | null): string {
  return value === null ? "—" : new Date(value).toLocaleString();
}

function deliveryColor(status: ExternalChannelDeliveryStatus): string {
  switch (status) {
    case "delivered":
      return "green";
    case "failed":
      return "red";
    case "unknown":
      return "yellow";
    case "attempting":
      return "blue";
    case "pending":
    case "not_attempted":
      return "gray";
  }
}

function workTask(value: Record<string, unknown>): WorkTask | null {
  const title = value.title;
  const status = value.status;
  if (
    typeof title !== "string" ||
    (status !== "pending" && status !== "in_progress" && status !== "completed")
  ) {
    return null;
  }
  return { title, status };
}

function projectionColor(state: ManagedWork["projection_state"]): string {
  switch (state) {
    case "synchronized":
      return "green";
    case "missing":
    case "stale":
      return "yellow";
    case "delete_failed":
      return "red";
    case "unknown":
      return "orange";
    case "none":
      return "gray";
  }
}

function DeliveryRow({
  delivery,
}: {
  delivery: ManagedDelivery;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.sessionChannels");
  return (
    <Group
      justify="space-between"
      align="flex-start"
      wrap="nowrap"
      py="xs"
      data-testid={`external-delivery-${delivery.id}`}
    >
      <Box style={{ minWidth: 0 }}>
        <Text size="sm" fw={600}>
          {t(`operation.${delivery.operation}`)}
        </Text>
        <Text size="xs" c="dimmed">
          {delivery.error_summary ??
            formatDate(delivery.completed_at ?? delivery.created_at)}
        </Text>
      </Box>
      <Badge color={deliveryColor(delivery.status)} variant="light">
        {t(`deliveryStatus.${delivery.status}`)}
      </Badge>
    </Group>
  );
}

function WorkSection({
  binding,
}: {
  binding: ManagedBinding;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.sessionChannels");
  if (binding.work === null) {
    return (
      <Text size="sm" c="dimmed">
        {t("noWork")}
      </Text>
    );
  }
  const tasks = binding.work.tasks
    .map(workTask)
    .filter((task): task is WorkTask => task !== null);

  return (
    <Stack gap="xs">
      <Group justify="space-between">
        <Group gap="xs">
          <Badge
            color={binding.work.status === "active" ? "blue" : "gray"}
            variant="light"
          >
            {t(`workStatus.${binding.work.status}`)}
          </Badge>
          <Text size="sm">
            {t("taskCount", { count: binding.work.tasks.length })}
          </Text>
        </Group>
        <Badge
          color={projectionColor(binding.work.projection_state)}
          variant="light"
        >
          {t(`projectionState.${binding.work.projection_state}`)}
        </Badge>
      </Group>
      {tasks.length > 0 && (
        <Stack gap="xs">
          {tasks.map((task, index) => (
            <Group key={`${index}-${task.title}`} gap="xs" wrap="nowrap">
              {task.status === "completed" ? (
                <IconCheck
                  size={rem(14)}
                  color="var(--mantine-color-green-6)"
                />
              ) : task.status === "in_progress" ? (
                <IconLoader2
                  size={rem(14)}
                  color="var(--mantine-color-blue-6)"
                />
              ) : (
                <IconClock size={rem(14)} color="var(--mantine-color-gray-6)" />
              )}
              <Text size="sm" style={{ flex: 1, overflowWrap: "anywhere" }}>
                {task.title}
              </Text>
              <Badge
                size="xs"
                variant="outline"
                color={
                  task.status === "completed"
                    ? "green"
                    : task.status === "in_progress"
                      ? "blue"
                      : "gray"
                }
              >
                {t(`taskStatus.${task.status}`)}
              </Badge>
            </Group>
          ))}
        </Stack>
      )}
      <Text size="xs" c="dimmed">
        {t("revisionDetail", {
          current: binding.work.state_revision,
          desired: binding.work.desired_progress_revision,
        })}
      </Text>
    </Stack>
  );
}

function BindingPanel({
  binding,
  archived,
  busy,
  actionsBusy,
  onDisconnect,
}: {
  binding: ManagedBinding;
  archived: boolean;
  busy: boolean;
  actionsBusy: boolean;
  onDisconnect: (binding: ManagedBinding) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.sessionChannels");
  const active = binding.status === "active";
  return (
    <Paper
      withBorder
      radius="lg"
      p="md"
      data-testid={`external-binding-${binding.id}`}
    >
      <Stack gap="md">
        <Group justify="space-between" align="flex-start" wrap="nowrap">
          <Box style={{ minWidth: 0 }}>
            <Group gap="xs">
              <Text fw={700}>{binding.resource_label}</Text>
              <Badge color={active ? "green" : "gray"} variant="light">
                {t(`bindingStatus.${binding.status}`)}
              </Badge>
              <Badge
                color={
                  binding.activation_status === "active" ? "blue" : "yellow"
                }
                variant="outline"
              >
                {t(`activationStatus.${binding.activation_status}`)}
              </Badge>
            </Group>
            <Text size="sm" c="dimmed" mt={4}>
              {binding.provider} · {binding.resource_type}
            </Text>
          </Box>
          <Button
            color="red"
            variant="subtle"
            size="xs"
            leftSection={<IconPlugConnectedX size={rem(14)} />}
            loading={busy}
            disabled={actionsBusy || !active || archived}
            onClick={() => onDisconnect(binding)}
          >
            {t("disconnect")}
          </Button>
        </Group>

        <SimpleGrid cols={{ base: 1, sm: 3 }} spacing="sm">
          <Box>
            <Text size="xs" c="dimmed" fw={700} tt="uppercase">
              {t("connectedAt")}
            </Text>
            <Text size="sm">{formatDate(binding.connected_at)}</Text>
          </Box>
          <Box>
            <Text size="xs" c="dimmed" fw={700} tt="uppercase">
              {t("latestActivity")}
            </Text>
            <Text size="sm">{formatDate(binding.latest_activity_at)}</Text>
          </Box>
          <Box>
            <Text size="xs" c="dimmed" fw={700} tt="uppercase">
              {t("retainedContext")}
            </Text>
            <Text size="sm">
              {t("truncationSummary", {
                messages: binding.truncated_message_count,
                bytes: binding.truncated_size,
              })}
            </Text>
          </Box>
        </SimpleGrid>

        {binding.disconnect_reason && (
          <Alert color="gray" title={t("disconnectReason")}>
            {binding.disconnect_reason}
          </Alert>
        )}

        <Divider label={t("channelWork")} labelPosition="left" />
        <WorkSection binding={binding} />

        <Divider label={t("deliveries")} labelPosition="left" />
        {binding.deliveries.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("noDeliveries")}
          </Text>
        ) : (
          <Stack gap={0}>
            {binding.deliveries.map((delivery, index) => (
              <Box key={delivery.id}>
                {index > 0 && <Divider />}
                <DeliveryRow delivery={delivery} />
              </Box>
            ))}
          </Stack>
        )}
      </Stack>
    </Paper>
  );
}

function GrantsPanel({
  grants,
}: {
  grants: ManagedGrant[];
}): React.ReactElement {
  const t = useTranslations("workspace.agents.sessionChannels");
  return (
    <Paper withBorder radius="lg" p="md">
      <Stack gap="sm">
        <Box>
          <Text fw={700}>{t("grantsTitle")}</Text>
          <Text size="sm" c="dimmed">
            {t("grantsDescription")}
          </Text>
        </Box>
        {grants.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("noGrants")}
          </Text>
        ) : (
          grants.map((grant, index) => (
            <Box key={grant.id}>
              {index > 0 && <Divider />}
              <Group gap="sm" py="xs">
                <IconShieldCheck
                  size={rem(18)}
                  color="var(--mantine-color-green-6)"
                />
                <Box>
                  <Text size="sm" fw={600}>
                    {grant.principal_label}
                  </Text>
                  <Text size="xs" c="dimmed">
                    {t(`grantScope.${grant.scope}`)}
                  </Text>
                </Box>
              </Group>
            </Box>
          ))
        )}
      </Stack>
    </Paper>
  );
}

export function SessionChannels({
  state,
  actionError,
  disconnectingId,
  onDisconnect,
}: SessionChannelsContainerOutput): React.ReactElement {
  const t = useTranslations("workspace.agents.sessionChannels");
  const modals = useModals();
  const openDisconnectConfirm = (binding: ManagedBinding): void => {
    modals.openConfirmModal({
      title: t("disconnect"),
      children: <Text size="sm">{t("disconnectConfirm")}</Text>,
      labels: { confirm: t("disconnect"), cancel: t("cancel") },
      confirmProps: { color: "red" },
      centered: true,
      onConfirm: () => onDisconnect(binding),
    });
  };

  return (
    <Box style={{ flex: 1, minHeight: 0, overflow: "auto" }}>
      <Stack gap="lg" p="lg" maw={rem(960)} mx="auto" w="100%">
        <Box>
          <Text fw={700} size="xl">
            {t("title")}
          </Text>
          <Text size="sm" c="dimmed">
            {t("description")}
          </Text>
        </Box>

        {actionError && <Alert color="red">{actionError}</Alert>}
        {state.type === "LOADING" && (
          <Center py="xl">
            <Loader size="sm" />
          </Center>
        )}
        {state.type === "ERROR" && <Alert color="red">{state.message}</Alert>}
        {state.type === "LOADED" && (
          <>
            {state.session.archived_at && (
              <Alert
                color="blue"
                icon={<IconArchive size={rem(16)} />}
                title={t("archivedTitle")}
              >
                <Stack gap={4}>
                  <Text size="sm">{t("archivedDescription")}</Text>
                  <Text size="sm">
                    {state.session.archive_retention_days_snapshot === null
                      ? t("retentionUnlimited")
                      : t("retentionDays", {
                          count: state.session.archive_retention_days_snapshot,
                        })}
                    {state.session.purge_after
                      ? ` · ${t("purgeAfter", {
                          value: formatDate(state.session.purge_after),
                        })}`
                      : ""}
                  </Text>
                </Stack>
              </Alert>
            )}

            {state.bindings.length === 0 ? (
              <Paper withBorder radius="lg" p="xl">
                <Stack align="center" gap="xs">
                  <Text fw={700}>{t("emptyTitle")}</Text>
                  <Text size="sm" c="dimmed" ta="center">
                    {t("emptyDescription")}
                  </Text>
                </Stack>
              </Paper>
            ) : (
              <Stack gap="sm">
                {state.bindings.map((binding) => (
                  <BindingPanel
                    key={binding.id}
                    binding={binding}
                    archived={state.session.archived_at !== null}
                    busy={disconnectingId === binding.id}
                    actionsBusy={disconnectingId !== null}
                    onDisconnect={openDisconnectConfirm}
                  />
                ))}
              </Stack>
            )}
            <GrantsPanel grants={state.grants} />
          </>
        )}
      </Stack>
    </Box>
  );
}
