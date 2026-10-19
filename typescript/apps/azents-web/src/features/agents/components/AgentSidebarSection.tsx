"use client";
import {
  ActionIcon,
  Box,
  Group,
  Loader,
  Stack,
  Text,
  TextInput,
  UnstyledButton,
} from "@mantine/core";
import { IconLayoutGrid, IconPlus, IconSearch } from "@tabler/icons-react";
/**
 * Sidebar agent section — exposes only pinned + recent (full directory is Home).
 *
 * Highlight current page agent.
 * Show up to 8 sorted by updated_at descending.
 * "+" creates new agent; footer "View all agents (N)" enters Home.
 */
import Link from "next/link";
import { useAgentSidebarSectionController } from "../containers/useAgentSidebarSectionController";
import { AgentSidebarRow } from "./AgentSidebarRow";
import type { AgentSidebarSectionViewProps } from "../containers/useAgentSidebarSectionController";
import type { AgentResponse } from "@azents/public-client";

interface AgentSidebarSectionProps {
  handle: string;
  onNavigate?: () => void;
}

export function AgentSidebarSection(
  props: AgentSidebarSectionProps,
): React.ReactElement {
  return (
    <AgentSidebarSectionView {...useAgentSidebarSectionController(props)} />
  );
}

export function AgentSidebarSectionView({
  onNavigate,
  t,
  workspaceBase,
  agentsBase,
  agentsQuery,
  activeAgentId,
  query,
  setQuery,
  sidebarAgents,
}: AgentSidebarSectionViewProps): React.ReactElement {
  return (
    <Stack gap={4}>
      <Group justify="space-between" px="xs" pt="xs">
        <Text
          size="xs"
          fw={600}
          c="dimmed"
          tt="uppercase"
          style={{ letterSpacing: 0.5 }}
        >
          {t("agentsSectionTitle")}
        </Text>
        <ActionIcon
          size="sm"
          variant="subtle"
          component={Link}
          href={`${agentsBase}/new`}
          onClick={onNavigate}
          title={t("newAgent")}
        >
          <IconPlus size={14} />
        </ActionIcon>
      </Group>
      <Box px="xs">
        <TextInput
          size="xs"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          placeholder={t("searchAgents")}
          leftSection={<IconSearch size={12} />}
        />
      </Box>
      <Box>
        {agentsQuery.isLoading ? (
          <Box ta="center" py="md">
            <Loader size="sm" />
          </Box>
        ) : sidebarAgents.visible.length === 0 ? (
          <Text size="xs" c="dimmed" ta="center" py="md">
            {query ? t("noMatches") : t("empty")}
          </Text>
        ) : (
          <AgentSidebarRowList
            agents={sidebarAgents.visible}
            agentsBase={agentsBase}
            activeAgentId={activeAgentId}
            onNavigate={onNavigate}
          />
        )}
      </Box>
      {sidebarAgents.totalCount > sidebarAgents.visible.length && (
        <UnstyledButton
          component={Link}
          href={workspaceBase}
          onClick={onNavigate}
          px="sm"
          py="xs"
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            fontSize: 12,
            color: "var(--mantine-color-dimmed)",
            borderRadius: "var(--mantine-radius-sm)",
          }}
        >
          <IconLayoutGrid size={13} />
          <Text size="xs" c="dimmed">
            {t("viewAllAgents", { count: sidebarAgents.totalCount })}
          </Text>
        </UnstyledButton>
      )}
    </Stack>
  );
}

interface RowListProps {
  agents: AgentResponse[];
  agentsBase: string;
  activeAgentId: string | null;
  onNavigate?: () => void;
}

function AgentSidebarRowList({
  agents,
  agentsBase,
  activeAgentId,
  onNavigate,
}: RowListProps): React.ReactElement {
  return (
    <>
      {agents.map((agent) => (
        <AgentSidebarRow
          key={agent.id}
          agent={agent}
          activeAgentId={activeAgentId}
          basePath={agentsBase}
          onNavigate={onNavigate}
        />
      ))}
    </>
  );
}
