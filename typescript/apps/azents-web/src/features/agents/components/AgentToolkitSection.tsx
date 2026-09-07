"use client";

/** Agent Toolkit management with an authority-gated enhanced flow. */

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Group,
  Loader,
  Modal,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconEdit, IconLink, IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useMemo, useState } from "react";
import { ToolkitFormPage } from "@/features/toolkits/ToolkitFormPage";
import { createReactContainer } from "@/shared/lib/createReactContainer";
import { trpc } from "@/trpc/client";
import {
  type AgentToolkitManagementContainerOutput,
  useAgentToolkitManagementContainer,
} from "../containers/useAgentToolkitManagementContainer";
import type {
  AgentToolkitManagementItemResponse,
  AgentToolkitResponse,
  ToolkitConfigResponse,
} from "@azents/public-client";

interface AgentToolkitSectionProps {
  handle: string;
  agentId: string;
  managementAvailable: boolean;
}

export function AgentToolkitSection({
  handle,
  agentId,
  managementAvailable,
}: AgentToolkitSectionProps): React.ReactElement {
  if (!managementAvailable) {
    return <LegacyAgentToolkitSection handle={handle} agentId={agentId} />;
  }
  return <ManagedAgentToolkitSection handle={handle} agentId={agentId} />;
}

export function ManagedAgentToolkitSectionView({
  handle,
  agentId,
  state,
  editor,
  mutationState,
  selectedToolkitId,
  deleteTarget,
  pending,
  attachPending,
  deletePending,
  onSelectedToolkitChange,
  onStartAdd,
  onToolkitTypeChange,
  onConfigureSelectedType,
  onEdit,
  onCloseEditor,
  onAttach,
  onDetach,
  onToggle,
  onRequestDelete,
  onCancelDelete,
  onConfirmDelete,
}: AgentToolkitManagementContainerOutput): React.ReactElement {
  const t = useTranslations("workspace.agents");
  if (editor.type === "CREATE" || editor.type === "EDIT") {
    return (
      <Stack id="agent-toolkits" gap="md">
        <ToolkitFormPage
          handle={handle}
          agentId={agentId}
          embedded
          onComplete={onCloseEditor}
          {...(editor.type === "CREATE" && {
            initialToolkitType: editor.toolkitType,
          })}
          {...(editor.type === "EDIT" && { toolkitId: editor.toolkitConfigId })}
        />
      </Stack>
    );
  }
  if (editor.type === "SELECT_TYPE") {
    const sharedOptions =
      state.type === "READY" && editor.toolkitType != null
        ? state.availableShared.filter(
            (toolkit) => toolkit.toolkitType === editor.toolkitType,
          )
        : [];
    return (
      <Stack id="agent-toolkits" gap="md">
        <Title order={3}>{t("toolkitManagement.addToolkit")}</Title>
        {mutationState.type === "ERROR" && (
          <Alert color="red">{mutationState.message}</Alert>
        )}
        <Select
          label={t("toolkitManagement.toolLabel")}
          placeholder={t("toolkitManagement.toolPlaceholder")}
          data={state.type === "READY" ? state.toolkitTypes : []}
          value={editor.toolkitType}
          onChange={onToolkitTypeChange}
          required
        />
        {editor.toolkitType != null && (
          <Stack gap="sm">
            <Card withBorder padding="sm">
              <Stack gap="xs">
                <Badge variant="outline" color="blue" w="fit-content">
                  {t("toolkitManagement.workspaceShared")}
                </Badge>
                <Text size="sm" fw={600}>
                  {t("toolkitManagement.attachShared")}
                </Text>
                <Text size="xs" c="dimmed">
                  {t("toolkitManagement.attachSharedDescription")}
                </Text>
                <Group align="flex-end">
                  <Select
                    aria-label={t("attachToolkit")}
                    placeholder={t("attachToolkit")}
                    data={sharedOptions}
                    value={selectedToolkitId}
                    onChange={onSelectedToolkitChange}
                    style={{ flex: 1 }}
                  />
                  <Button
                    variant="light"
                    leftSection={<IconLink size={14} />}
                    disabled={selectedToolkitId == null}
                    loading={attachPending}
                    onClick={onAttach}
                  >
                    {t("toolkitManagement.attach")}
                  </Button>
                </Group>
                {sharedOptions.length === 0 && (
                  <Text size="xs" c="dimmed">
                    {t("toolkitManagement.noSharedForType")}
                  </Text>
                )}
              </Stack>
            </Card>
            <Card withBorder padding="sm">
              <Stack gap="xs" align="flex-start">
                <Badge variant="outline" color="violet">
                  {t("toolkitManagement.agentOnly")}
                </Badge>
                <Text size="xs" c="dimmed">
                  {t("toolkitManagement.agentOnlyDescription")}
                </Text>
                <Button onClick={onConfigureSelectedType}>
                  {t("toolkitManagement.configureForAgent")}
                </Button>
              </Stack>
            </Card>
          </Stack>
        )}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCloseEditor}>
            {t("cancel")}
          </Button>
        </Group>
      </Stack>
    );
  }
  return (
    <Stack id="agent-toolkits" gap="md">
      <Group justify="space-between" align="flex-start">
        <Stack gap={2}>
          <Title order={5}>{t("toolkitsSection")}</Title>
          <Text size="sm" c="dimmed">
            {t("toolkitManagement.description")}
          </Text>
        </Stack>
        <Button
          size="xs"
          leftSection={<IconPlus size={14} />}
          disabled={state.type !== "READY"}
          onClick={onStartAdd}
        >
          {t("toolkitManagement.addToolkit")}
        </Button>
      </Group>
      {state.type === "LOADING" && <Loader size="sm" />}
      {state.type === "ERROR" && (
        <Alert color="red">{state.message || t("toolkitLoadError")}</Alert>
      )}
      {mutationState.type === "ERROR" && (
        <Alert color="red">{mutationState.message}</Alert>
      )}
      {state.type === "READY" && (
        <>
          <Stack gap="xs">
            {state.items.length === 0 && (
              <Text size="sm" c="dimmed">
                {t("noToolkitsAttached")}
              </Text>
            )}
            {state.items.map((item) => (
              <ManagedToolkitCard
                key={`${item.ownership_scope}:${item.toolkit.id}`}
                item={item}
                pending={pending}
                onDetach={() => {
                  if (item.agent_toolkit_id) {
                    onDetach(item.agent_toolkit_id);
                  }
                }}
                onEdit={() => onEdit(item.toolkit.id)}
                onToggle={() => onToggle(item)}
                onDelete={() => onRequestDelete(item)}
              />
            ))}
          </Stack>
        </>
      )}
      <Modal
        opened={deleteTarget != null}
        onClose={onCancelDelete}
        title={t("toolkitManagement.deleteTitle")}
        centered
      >
        <Stack>
          <Text size="sm">
            {t("toolkitManagement.deleteDescription", {
              name: deleteTarget?.toolkit.name ?? "",
            })}
          </Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={onCancelDelete}>
              {t("cancel")}
            </Button>
            <Button
              color="red"
              loading={deletePending}
              onClick={onConfirmDelete}
            >
              {t("toolkitManagement.deleteConfirm")}
            </Button>
          </Group>
        </Stack>
      </Modal>
    </Stack>
  );
}

const ManagedAgentToolkitSection = createReactContainer(
  "ManagedAgentToolkitSection",
  useAgentToolkitManagementContainer,
  ManagedAgentToolkitSectionView,
);

export interface ManagedToolkitCardProps {
  item: AgentToolkitManagementItemResponse;
  pending: boolean;
  onDetach: () => void;
  onEdit: () => void;
  onToggle: () => void;
  onDelete: () => void;
}

export function ManagedToolkitCard({
  item,
  pending,
  onDetach,
  onEdit,
  onToggle,
  onDelete,
}: ManagedToolkitCardProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const shared = item.ownership_scope === "workspace_shared";
  return (
    <Card withBorder padding="sm">
      <Stack gap="xs">
        <Group justify="space-between" align="flex-start">
          <Stack gap={3}>
            <Group gap="xs">
              <Text fw={600}>{item.toolkit.name}</Text>
              <Badge variant="light">{item.toolkit.toolkit_type}</Badge>
            </Group>
            <Group gap="xs">
              <Badge color={shared ? "blue" : "violet"} variant="outline">
                {shared
                  ? t("toolkitManagement.workspaceShared")
                  : t("toolkitManagement.agentOnly")}
              </Badge>
              <Badge
                color={
                  item.readiness === "ready"
                    ? "green"
                    : item.readiness === "disabled"
                      ? "gray"
                      : "orange"
                }
              >
                {t(`toolkitManagement.readiness.${item.readiness}`)}
              </Badge>
            </Group>
          </Stack>
          {shared ? (
            <Button
              size="xs"
              variant="subtle"
              color="red"
              leftSection={<IconTrash size={14} />}
              disabled={pending}
              onClick={onDetach}
            >
              {t("toolkitManagement.detach")}
            </Button>
          ) : (
            <Group gap={4}>
              <ActionIcon
                variant="subtle"
                aria-label={t("toolkitManagement.edit")}
                disabled={pending}
                onClick={onEdit}
              >
                <IconEdit size={16} />
              </ActionIcon>
              <Button
                size="xs"
                variant="subtle"
                disabled={pending}
                onClick={onToggle}
              >
                {item.toolkit.enabled
                  ? t("toolkitManagement.disable")
                  : t("toolkitManagement.enable")}
              </Button>
              <ActionIcon
                variant="subtle"
                color="red"
                aria-label={t("toolkitManagement.delete")}
                disabled={pending}
                onClick={onDelete}
              >
                <IconTrash size={16} />
              </ActionIcon>
            </Group>
          )}
        </Group>
        {item.toolkit.description && (
          <Text size="sm" c="dimmed">
            {item.toolkit.description}
          </Text>
        )}
        {shared && (
          <Text size="xs" c="dimmed">
            {t("toolkitManagement.workspaceBoundary")}
          </Text>
        )}
      </Stack>
    </Card>
  );
}

function LegacyAgentToolkitSection({
  handle,
  agentId,
}: Omit<AgentToolkitSectionProps, "managementAvailable">): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const utils = trpc.useUtils();
  const [selectedToolkitId, setSelectedToolkitId] = useState<string | null>(
    null,
  );
  const agentToolkitsQuery = trpc.toolkit.listAgentToolkits.useQuery({
    handle,
    agentId,
  });
  const availableToolkitsQuery = trpc.toolkit.listAvailableConfigs.useQuery({
    handle,
  });
  const agentToolkits: AgentToolkitResponse[] = useMemo(
    () => agentToolkitsQuery.data?.items ?? [],
    [agentToolkitsQuery.data],
  );
  const availableToolkits: ToolkitConfigResponse[] = useMemo(
    () => availableToolkitsQuery.data?.items ?? [],
    [availableToolkitsQuery.data],
  );
  const attachedToolkitIds = useMemo(
    () => new Set(agentToolkits.map((item) => item.toolkit_id)),
    [agentToolkits],
  );
  const selectOptions = useMemo(
    () =>
      availableToolkits
        .filter((toolkit) => !attachedToolkitIds.has(toolkit.id))
        .map((toolkit) => ({
          value: toolkit.id,
          label: `${toolkit.name} (${toolkit.toolkit_type})`,
        })),
    [attachedToolkitIds, availableToolkits],
  );
  const attachMutation = trpc.toolkit.attachToAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
      setSelectedToolkitId(null);
    },
  });
  const detachMutation = trpc.toolkit.detachFromAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
    },
  });
  const loading =
    agentToolkitsQuery.isLoading || availableToolkitsQuery.isLoading;
  const failed = agentToolkitsQuery.isError || availableToolkitsQuery.isError;
  return (
    <Stack id="agent-toolkits" gap="sm">
      <Title order={5}>{t("toolkitsSection")}</Title>
      {loading && <Loader size="sm" />}
      {failed && <Alert color="red">{t("toolkitLoadError")}</Alert>}
      {!loading && !failed && agentToolkits.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("noToolkitsAttached")}
        </Text>
      )}
      {agentToolkits.map((item) => (
        <Group key={item.id} gap="sm">
          <Badge variant="light" size="sm">
            {item.toolkit_type}
          </Badge>
          <Text size="sm" style={{ flex: 1 }}>
            {availableToolkits.find((toolkit) => toolkit.id === item.toolkit_id)
              ?.name ?? item.toolkit_id}
          </Text>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            aria-label={t("toolkitManagement.detach")}
            onClick={() =>
              detachMutation.mutate({
                handle,
                agentId,
                agentToolkitId: item.id,
              })
            }
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      ))}
      {!loading && !failed && selectOptions.length > 0 && (
        <Group gap="sm">
          <Select
            placeholder={t("attachToolkit")}
            data={selectOptions}
            value={selectedToolkitId}
            onChange={setSelectedToolkitId}
            size="sm"
            style={{ flex: 1 }}
          />
          <ActionIcon
            variant="light"
            size="lg"
            aria-label={t("toolkitManagement.attach")}
            disabled={selectedToolkitId == null}
            onClick={() => {
              if (selectedToolkitId) {
                attachMutation.mutate({
                  handle,
                  agentId,
                  toolkitId: selectedToolkitId,
                });
              }
            }}
          >
            <IconLink size={16} />
          </ActionIcon>
        </Group>
      )}
      {!loading &&
        !failed &&
        selectOptions.length === 0 &&
        availableToolkits.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("noToolkitsAvailable")}
          </Text>
        )}
    </Stack>
  );
}
