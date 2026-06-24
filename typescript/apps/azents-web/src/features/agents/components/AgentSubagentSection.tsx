"use client";

/**
 * Subagent management section connected to Agent.
 *
 * Handles subagent attach/detach in Agent edit form.
 */

import {
  ActionIcon,
  Alert,
  Group,
  Loader,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { IconLink, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";

interface AgentSubagentSectionProps {
  handle: string;
  agentId: string;
}

export function AgentSubagentSection({
  handle,
  agentId,
}: AgentSubagentSectionProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const utils = trpc.useUtils();

  const [selectedSubagentId, setSelectedSubagentId] = useState<string | null>(
    null,
  );
  const [newDescription, setNewDescription] = useState("");

  // Subagent list connected to Agent
  const subagentListQuery = trpc.agentSubagent.list.useQuery({
    handle,
    agentId,
  });

  // Available Agent list (only role=subagent selectable)
  const agentListQuery = trpc.agent.list.useQuery({ handle });

  const connectedSubagents = useMemo(
    () => subagentListQuery.data?.items ?? [],
    [subagentListQuery.data],
  );

  const connectedSubagentIds = useMemo(
    () => new Set(connectedSubagents.map((s) => s.subagent_id)),
    [connectedSubagents],
  );

  // Filter only role=subagent, enabled=true, not already connected
  const availableSubagents = useMemo(() => {
    const agents = agentListQuery.data?.items ?? [];
    return agents.filter(
      (a) =>
        a.role === "subagent" && a.enabled && !connectedSubagentIds.has(a.id),
    );
  }, [agentListQuery.data, connectedSubagentIds]);

  const selectOptions = useMemo(
    () =>
      availableSubagents.map((a) => ({
        value: a.id,
        label: a.name,
      })),
    [availableSubagents],
  );

  // Attach mutation
  const createMutation = trpc.agentSubagent.create.useMutation({
    onSuccess: () => {
      void utils.agentSubagent.list.invalidate({ handle, agentId });
      setSelectedSubagentId(null);
      setNewDescription("");
    },
  });

  // Update mutation
  const updateMutation = trpc.agentSubagent.update.useMutation({
    onSuccess: () => {
      void utils.agentSubagent.list.invalidate({ handle, agentId });
    },
  });

  // Delete mutation
  const removeMutation = trpc.agentSubagent.remove.useMutation({
    onSuccess: () => {
      void utils.agentSubagent.list.invalidate({ handle, agentId });
    },
  });

  const handleAdd = useCallback(() => {
    if (!selectedSubagentId || !newDescription) {
      return;
    }
    createMutation.mutate({
      handle,
      agentId,
      subagentId: selectedSubagentId,
      description: newDescription,
    });
  }, [handle, agentId, selectedSubagentId, newDescription, createMutation]);

  const handleToggleEnabled = useCallback(
    (agentSubagentId: string, enabled: boolean) => {
      updateMutation.mutate({
        handle,
        agentId,
        agentSubagentId,
        enabled,
      });
    },
    [handle, agentId, updateMutation],
  );

  const handleRemove = useCallback(
    (agentSubagentId: string) => {
      removeMutation.mutate({ handle, agentId, agentSubagentId });
    },
    [handle, agentId, removeMutation],
  );

  // Agent name lookup helper
  const getAgentName = useCallback(
    (subagentId: string): string => {
      const agents = agentListQuery.data?.items ?? [];
      return agents.find((a) => a.id === subagentId)?.name ?? subagentId;
    },
    [agentListQuery.data],
  );

  const isLoading = subagentListQuery.isLoading || agentListQuery.isLoading;
  const hasError = subagentListQuery.isError || agentListQuery.isError;

  return (
    <Stack gap="sm">
      <Title order={5}>{t("subagentsSection")}</Title>

      {isLoading && <Loader size="sm" />}

      {hasError && (
        <Alert color="red">
          {subagentListQuery.error?.message ??
            agentListQuery.error?.message ??
            "Failed to load subagents"}
        </Alert>
      )}

      {!isLoading && !hasError && connectedSubagents.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("noSubagentsAttached")}
        </Text>
      )}

      {connectedSubagents.map((sub) => (
        <Stack key={sub.id} gap={4}>
          <Group gap="sm">
            <Text size="sm" fw={500}>
              {getAgentName(sub.subagent_id)}
            </Text>
            <Text size="xs" c="dimmed" style={{ flex: 1 }}>
              {sub.description}
            </Text>
            <Switch
              size="xs"
              checked={sub.enabled}
              onChange={(e) =>
                handleToggleEnabled(sub.id, e.currentTarget.checked)
              }
            />
            <ActionIcon
              variant="subtle"
              color="red"
              size="sm"
              onClick={() => handleRemove(sub.id)}
            >
              <IconTrash size={14} />
            </ActionIcon>
          </Group>
        </Stack>
      ))}

      {!isLoading && !hasError && selectOptions.length > 0 && (
        <Stack gap="xs">
          <Group gap="sm">
            <Select
              placeholder={t("selectSubagent")}
              data={selectOptions}
              value={selectedSubagentId}
              onChange={setSelectedSubagentId}
              size="sm"
              style={{ flex: 1 }}
            />
          </Group>
          <Group gap="sm">
            <TextInput
              placeholder={t("subagentDescriptionPlaceholder")}
              value={newDescription}
              onChange={(e) => setNewDescription(e.currentTarget.value)}
              size="sm"
              style={{ flex: 1 }}
            />
            <ActionIcon
              variant="light"
              size="lg"
              onClick={handleAdd}
              disabled={!selectedSubagentId || !newDescription}
            >
              <IconLink size={16} />
            </ActionIcon>
          </Group>
        </Stack>
      )}

      {!isLoading &&
        !hasError &&
        selectOptions.length === 0 &&
        availableSubagents.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("noSubagentsAvailable")}
          </Text>
        )}
    </Stack>
  );
}
