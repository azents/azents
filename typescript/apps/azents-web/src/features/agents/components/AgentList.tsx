"use client";

/**
 * Agent list UI component.
 *
 * Displays Agent card list and provides delete/enabled toggle.
 * Clicking card moves to edit page.
 */

import {
  ActionIcon,
  Alert,
  Badge,
  Button,
  Card,
  Container,
  Group,
  Loader,
  Modal,
  SegmentedControl,
  Stack,
  Switch,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { IconEdit, IconPlus, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { formatModelSelectionSummary } from "../model-selection";
import type { AgentListContainerOutput } from "../containers/useAgentListContainer";
import type { AgentResponse } from "@azents/public-client";

export function AgentList(props: AgentListContainerOutput): React.ReactElement {
  const {
    handle,
    listState,
    canManage,
    roleFilter,
    counts,
    onRoleFilterChange,
    onDelete,
    onToggleEnabled,
  } = props;
  const t = useTranslations("workspace.agents");

  const filterOptions = useMemo(
    () => [
      {
        value: "agent" as const,
        label: `${t("roleFilter.agent")} (${counts.agent})`,
      },
      {
        value: "subagent" as const,
        label: `${t("roleFilter.subagent")} (${counts.subagent})`,
      },
      {
        value: "all" as const,
        label: `${t("roleFilter.all")} (${counts.all})`,
      },
    ],
    [t, counts],
  );

  const [deleteOpened, { open: openDelete, close: closeDelete }] =
    useDisclosure(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const handleDeleteClick = useCallback(
    (agentId: string): void => {
      setDeleteTarget(agentId);
      openDelete();
    },
    [openDelete],
  );

  const handleDeleteConfirm = useCallback((): void => {
    if (deleteTarget) {
      onDelete(deleteTarget);
      setDeleteTarget(null);
      closeDelete();
    }
  }, [deleteTarget, onDelete, closeDelete]);

  const basePath = `/w/${handle}/agents`;

  return (
    <Container size="md" py="xl">
      <Stack gap="lg">
        <Group justify="space-between">
          <Title order={3}>{t("headline")}</Title>
          <Button
            component={Link}
            href={`${basePath}/new`}
            leftSection={<IconPlus size={16} />}
          >
            {t("addAgent")}
          </Button>
        </Group>

        <Text c="dimmed" size="sm">
          {t("description")}
        </Text>

        <SegmentedControl
          value={roleFilter}
          onChange={(value) => onRoleFilterChange(value)}
          data={filterOptions}
          fullWidth
        />

        {listState.type === "LOADING" && <Loader />}
        {listState.type === "ERROR" && (
          <Alert color="red">{t("loadError")}</Alert>
        )}
        {listState.type === "READY" && listState.agents.length === 0 && (
          <Text c="dimmed">
            {counts.all === 0
              ? t("empty")
              : t(`emptyForFilter.${roleFilter}` as const)}
          </Text>
        )}
        {listState.type === "READY" &&
          listState.agents.map((agent) => (
            <AgentCard
              key={agent.id}
              agent={agent}
              basePath={basePath}
              canManage={canManage}
              onDelete={handleDeleteClick}
              onToggleEnabled={onToggleEnabled}
            />
          ))}

        <Modal
          opened={deleteOpened}
          onClose={closeDelete}
          title={t("delete")}
          centered
        >
          <Stack gap="md">
            <Text>{t("deleteConfirm")}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={closeDelete}>
                {t("cancel")}
              </Button>
              <Button color="red" onClick={handleDeleteConfirm}>
                {t("delete")}
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Stack>
    </Container>
  );
}

/** Agent card */
function AgentCard({
  agent,
  basePath,
  canManage,
  onDelete,
  onToggleEnabled,
}: {
  agent: AgentResponse;
  basePath: string;
  canManage: boolean;
  onDelete: (agentId: string) => void;
  onToggleEnabled: (agent: AgentResponse, enabled: boolean) => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const modelSummary = formatModelSelectionSummary(agent.model_selection);

  return (
    <Card withBorder padding="md">
      <Group justify="space-between" wrap="nowrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="sm">
            <Badge
              color={agent.model_selection ? "blue" : "gray"}
              variant="light"
              size="sm"
            >
              {modelSummary}
            </Badge>
            <Text fw={500} truncate>
              {agent.name}
            </Text>
            {agent.role === "subagent" && (
              <Badge color="violet" variant="light" size="sm">
                {t("roleFilter.subagent")}
              </Badge>
            )}
            {!agent.enabled && (
              <Badge color="gray" variant="outline" size="sm">
                {t("disabled")}
              </Badge>
            )}
          </Group>
          {agent.description && (
            <Text size="sm" c="dimmed" lineClamp={1}>
              {agent.description}
            </Text>
          )}
          <Group gap="xs">
            <Badge variant="dot" size="xs">
              {agent.type === "public" ? t("public") : t("private")}
            </Badge>
            <Text size="xs" c="dimmed">
              {modelSummary}
            </Text>
          </Group>
        </Stack>

        <Group gap="xs" wrap="nowrap">
          {canManage && (
            <Switch
              checked={agent.enabled}
              onChange={(e) => onToggleEnabled(agent, e.currentTarget.checked)}
              size="sm"
            />
          )}
          <ActionIcon
            component={Link}
            href={`${basePath}/${agent.id}`}
            variant="subtle"
            title={t("open")}
          >
            <IconEdit size={16} />
          </ActionIcon>
          {canManage && (
            <ActionIcon
              variant="subtle"
              color="red"
              onClick={() => onDelete(agent.id)}
            >
              <IconTrash size={16} />
            </ActionIcon>
          )}
        </Group>
      </Group>
    </Card>
  );
}
