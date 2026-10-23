"use client";
import {
  ActionIcon,
  Box,
  Group,
  Loader,
  rem,
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
  state,
  activeAgentId,
  query,
  setQuery,
}: AgentSidebarSectionViewProps): React.ReactElement {
  return (
    <Stack gap={4}>
      <Group justify="space-between" px="xs" pt="xs">
        <Text
          size="xs"
          fw={600}
          c="dimmed"
          tt="uppercase"
          style={{ letterSpacing: rem(0.5) }}
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
          <IconPlus size={rem(14)} />
        </ActionIcon>
      </Group>
      <Box px="xs">
        <TextInput
          size="xs"
          value={query}
          onChange={(e) => setQuery(e.currentTarget.value)}
          placeholder={t("searchAgents")}
          leftSection={<IconSearch size={rem(12)} />}
        />
      </Box>
      <Box>
        {state.type === "LOADING" ? (
          <Box ta="center" py="md">
            <Loader size="sm" />
          </Box>
        ) : state.visible.length === 0 ? (
          <Text size="xs" c="dimmed" ta="center" py="md">
            {query ? t("noMatches") : t("empty")}
          </Text>
        ) : (
          <AgentSidebarRowList
            agents={state.visible}
            agentsBase={agentsBase}
            activeAgentId={activeAgentId}
            onNavigate={onNavigate}
          />
        )}
      </Box>
      {state.type === "READY" && state.totalCount > state.visible.length && (
        <UnstyledButton
          component={Link}
          href={workspaceBase}
          onClick={onNavigate}
          px="sm"
          py="xs"
          style={{
            display: "flex",
            alignItems: "center",
            gap: rem(8),
            fontSize: rem(12),
            color: "var(--mantine-color-dimmed)",
            borderRadius: "var(--mantine-radius-sm)",
          }}
        >
          <IconLayoutGrid size={rem(13)} />
          <Text size="xs" c="dimmed">
            {t("viewAllAgents", { count: state.totalCount })}
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
