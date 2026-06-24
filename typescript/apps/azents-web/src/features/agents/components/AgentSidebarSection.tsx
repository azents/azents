"use client";

/**
 * Sidebar agent section — exposes only pinned + recent (full directory is Home).
 *
 * Highlight current page agent.
 * Show up to 8 sorted by updated_at descending.
 * "+" creates new agent; footer "View all agents (N)" enters Home.
 */

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
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { AgentSidebarRow } from "./AgentSidebarRow";
import type { AgentResponse } from "@azents/public-client";

interface AgentSidebarSectionProps {
  handle: string;
  onNavigate?: () => void;
}

/** Maximum agents exposed in sidebar (pinned + recent combined) */
const MAX_SIDEBAR_ROWS = 8;
/** Extract active agent/session ID from pathname */
function resolveActive(
  pathname: string,
  basePath: string,
): {
  agentId: string | null;
} {
  if (!pathname.startsWith(basePath)) {
    return { agentId: null };
  }
  const rest = pathname.slice(basePath.length + 1); // after basePath + "/"
  const parts = rest.split("/");
  // rest is like "agents/{agentId}/chat/{sessionId?}"
  if (parts[0] === "agents" && parts[1] && parts[1] !== "new") {
    const agentId = parts[1];
    return { agentId };
  }
  return { agentId: null };
}

export function AgentSidebarSection({
  handle,
  onNavigate,
}: AgentSidebarSectionProps): React.ReactElement {
  const t = useTranslations("workspace.sidebar");
  const pathname = usePathname();
  const workspaceBase = `/w/${handle}`;
  const agentsBase = `${workspaceBase}/agents`;

  const agentsQuery = trpc.agent.list.useQuery({ handle });

  const { agentId: activeAgentId } = useMemo(
    () => resolveActive(pathname, workspaceBase),
    [pathname, workspaceBase],
  );

  const [query, setQuery] = useState("");

  const sidebarAgents = useMemo(() => {
    const items = agentsQuery.data?.items ?? [];
    const q = query.toLowerCase();
    const filtered = items
      .filter((a) => a.role !== "subagent" && a.enabled)
      .filter(
        (a) =>
          !q ||
          a.name.toLowerCase().includes(q) ||
          (a.description ?? "").toLowerCase().includes(q),
      );

    // Separately pick active agent to always include it.
    const alwaysInclude = activeAgentId
      ? filtered.filter((agent) => agent.id === activeAgentId)
      : [];
    const recent = filtered
      .filter((agent) => agent.id !== activeAgentId)
      .sort(
        (a, b) =>
          new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime(),
      );

    const slots = Math.max(0, MAX_SIDEBAR_ROWS - alwaysInclude.length);
    const visible = [...alwaysInclude, ...recent.slice(0, slots)];
    return { visible, totalCount: filtered.length };
  }, [agentsQuery.data, query, activeAgentId]);

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
