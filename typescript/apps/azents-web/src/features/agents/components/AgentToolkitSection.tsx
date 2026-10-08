"use client";

/** Saved-Agent management retains the existing non-administrator boundary. */
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
import { useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { ManagedAgentToolkitSection } from "./ManagedAgentToolkitSection";
import type {
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
  return managementAvailable ? (
    <ManagedAgentToolkitSection handle={handle} agentId={agentId} />
  ) : (
    <LegacyAgentToolkitSection handle={handle} agentId={agentId} />
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
