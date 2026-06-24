"use client";

/**
 * Toolkit management section connected to Agent.
 *
 * Handles Toolkit attach/detach in Agent edit form.
 */

import {
  ActionIcon,
  Alert,
  Badge,
  Group,
  Loader,
  Select,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { IconLink, IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import type {
  AgentToolkitResponse,
  ToolkitConfigResponse,
} from "@azents/public-client";

interface AgentToolkitSectionProps {
  handle: string;
  agentId: string;
}

export function AgentToolkitSection({
  handle,
  agentId,
}: AgentToolkitSectionProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const utils = trpc.useUtils();

  const [selectedToolkitId, setSelectedToolkitId] = useState<string | null>(
    null,
  );

  // Toolkit list connected to Agent
  const agentToolkitsQuery = trpc.toolkit.listAgentToolkits.useQuery({
    handle,
    agentId,
  });

  // Available Toolkit Config list
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

  // Show only not-yet-connected Toolkit as selectable options
  const attachedToolkitIds = useMemo(
    () => new Set(agentToolkits.map((at) => at.toolkit_id)),
    [agentToolkits],
  );

  const selectOptions = useMemo(
    () =>
      availableToolkits
        .filter((tk) => !attachedToolkitIds.has(tk.id))
        .map((tk) => ({
          value: tk.id,
          label: `${tk.name} (${tk.toolkit_type})`,
        })),
    [availableToolkits, attachedToolkitIds],
  );

  // Attach mutation
  const attachMutation = trpc.toolkit.attachToAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
      setSelectedToolkitId(null);
    },
  });

  // Detach mutation
  const detachMutation = trpc.toolkit.detachFromAgent.useMutation({
    onSuccess: () => {
      void utils.toolkit.listAgentToolkits.invalidate({ handle, agentId });
    },
  });

  const handleAttach = useCallback(() => {
    if (!selectedToolkitId) {
      return;
    }
    attachMutation.mutate({ handle, agentId, toolkitId: selectedToolkitId });
  }, [handle, agentId, selectedToolkitId, attachMutation]);

  const handleDetach = useCallback(
    (agentToolkitId: string) => {
      detachMutation.mutate({ handle, agentId, agentToolkitId });
    },
    [handle, agentId, detachMutation],
  );

  const isLoading =
    agentToolkitsQuery.isLoading || availableToolkitsQuery.isLoading;
  const hasError = agentToolkitsQuery.isError || availableToolkitsQuery.isError;

  return (
    <Stack gap="sm">
      <Title order={5}>{t("toolkitsSection")}</Title>

      {isLoading && <Loader size="sm" />}

      {hasError && (
        <Alert color="red">
          {availableToolkitsQuery.error?.message ??
            agentToolkitsQuery.error?.message ??
            t("toolkitLoadError")}
        </Alert>
      )}

      {!isLoading && !hasError && agentToolkits.length === 0 && (
        <Text size="sm" c="dimmed">
          {t("noToolkitsAttached")}
        </Text>
      )}

      {agentToolkits.map((at) => (
        <Group key={at.id} gap="sm">
          <Badge variant="light" size="sm">
            {at.toolkit_type}
          </Badge>
          <Text size="sm" style={{ flex: 1 }}>
            {availableToolkits.find((tk) => tk.id === at.toolkit_id)?.name ??
              at.toolkit_id}
          </Text>
          <ActionIcon
            variant="subtle"
            color="red"
            size="sm"
            onClick={() => handleDetach(at.id)}
          >
            <IconTrash size={14} />
          </ActionIcon>
        </Group>
      ))}

      {!isLoading && !hasError && selectOptions.length > 0 && (
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
            onClick={handleAttach}
            disabled={!selectedToolkitId}
          >
            <IconLink size={16} />
          </ActionIcon>
        </Group>
      )}

      {!isLoading &&
        !hasError &&
        selectOptions.length === 0 &&
        availableToolkits.length === 0 && (
          <Text size="sm" c="dimmed">
            {t("noToolkitsAvailable")}
          </Text>
        )}
    </Stack>
  );
}
