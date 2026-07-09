"use client";

/** Subagent Tree navigation panel. */

import {
  Badge,
  Box,
  Center,
  Divider,
  Group,
  Loader,
  rem,
  ScrollArea,
  Stack,
  Text,
  ThemeIcon,
  UnstyledButton,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconCircleCheck,
  IconClock,
  IconGitBranch,
  IconMessageCircle,
  IconPlayerPause,
  IconRobot,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import type {
  SubagentTreeNodeResponse,
  SubagentTreeResponse,
} from "@azents/public-client";

export type SubagentTreePanelState =
  | { type: "LOADING" }
  | { type: "ERROR"; message: string }
  | { type: "LOADED"; tree: SubagentTreeResponse };

interface SubagentTreePanelProps {
  handle: string;
  agentId: string;
  activeSessionId: string;
  state: SubagentTreePanelState;
  onNavigate?: () => void;
}

function countNodes(nodes: SubagentTreeNodeResponse[]): number {
  return nodes.reduce(
    (total, node) => total + 1 + countNodes(node.children ?? []),
    0,
  );
}

function countChildren(nodes: SubagentTreeNodeResponse[]): number {
  return nodes.reduce(
    (total, node) => total + countNodes(node.children ?? []),
    0,
  );
}

function statusColor(status: string): string {
  switch (status) {
    case "running":
      return "blue";
    case "completed":
      return "green";
    case "errored":
      return "red";
    case "interrupted":
      return "yellow";
    case "idle":
      return "gray";
    default:
      return "gray";
  }
}

function statusLabel(
  status: string,
  t: ReturnType<typeof useTranslations>,
): string {
  switch (status) {
    case "running":
      return t("subagents.status.running");
    case "completed":
      return t("subagents.status.completed");
    case "errored":
      return t("subagents.status.errored");
    case "interrupted":
      return t("subagents.status.interrupted");
    case "idle":
      return t("subagents.status.idle");
    case "not_found":
      return t("subagents.status.notFound");
    default:
      return status;
  }
}

function statusIcon(status: string): React.ReactElement {
  switch (status) {
    case "running":
      return <Loader size={rem(14)} />;
    case "completed":
      return <IconCircleCheck size={rem(14)} />;
    case "errored":
      return <IconAlertCircle size={rem(14)} />;
    case "interrupted":
      return <IconPlayerPause size={rem(14)} />;
    default:
      return <IconClock size={rem(14)} />;
  }
}

function SubagentNodeRow({
  handle,
  agentId,
  node,
  activeSessionId,
  activeSessionAgentId,
  rootSessionAgentId,
  depth,
  onNavigate,
}: {
  handle: string;
  agentId: string;
  node: SubagentTreeNodeResponse;
  activeSessionId: string;
  activeSessionAgentId: string;
  rootSessionAgentId: string;
  depth: number;
  onNavigate?: () => void;
}): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const active =
    node.session_agent_id === activeSessionAgentId ||
    node.agent_session_id === activeSessionId;
  const root = node.session_agent_id === rootSessionAgentId;
  const href = `/w/${handle}/agents/${agentId}/sessions/${node.agent_session_id}`;
  const children = node.children ?? [];

  return (
    <Stack gap={0}>
      <UnstyledButton
        component={Link}
        href={href}
        onClick={onNavigate}
        p="xs"
        style={{
          borderRadius: "var(--mantine-radius-md)",
          backgroundColor: active
            ? "var(--mantine-primary-color-light)"
            : "transparent",
          color: active
            ? "var(--mantine-primary-color-light-color)"
            : "inherit",
        }}
      >
        <Group gap="xs" wrap="nowrap" align="flex-start">
          <Box
            aria-hidden="true"
            style={{
              flexShrink: 0,
              paddingLeft: rem(depth * 14),
              paddingTop: rem(2),
            }}
          >
            <ThemeIcon
              variant={active ? "filled" : "light"}
              color={statusColor(node.status)}
              size="sm"
              radius="xl"
            >
              {root ? <IconRobot size={rem(14)} /> : statusIcon(node.status)}
            </ThemeIcon>
          </Box>
          <Stack gap="xs" style={{ minWidth: 0, flex: 1 }}>
            <Group gap="xs" wrap="nowrap">
              <Text size="sm" fw={active ? 700 : 600} truncate>
                {node.name}
              </Text>
              {root && (
                <Badge size="xs" variant="light">
                  {t("subagents.rootBadge")}
                </Badge>
              )}
              {!root && node.unread_result && (
                <Badge size="xs" color="blue" variant="filled">
                  {t("subagents.unread")}
                </Badge>
              )}
            </Group>
            <Group gap="xs" wrap="wrap">
              <Badge size="xs" variant="light" color={statusColor(node.status)}>
                {statusLabel(node.status, t)}
              </Badge>
              {node.latest_run_index !== null &&
                typeof node.latest_run_index !== "undefined" && (
                  <Badge size="xs" variant="default">
                    {t("subagents.runIndex", {
                      index: node.latest_run_index,
                    })}
                  </Badge>
                )}
            </Group>
            {node.last_task_message && (
              <Text size="xs" c="dimmed" lineClamp={2}>
                {node.last_task_message}
              </Text>
            )}
            {node.terminal_result_message && (
              <Group gap="xs" wrap="nowrap" c="dimmed">
                <IconMessageCircle size={rem(12)} />
                <Text size="xs" lineClamp={2} style={{ minWidth: 0 }}>
                  {node.terminal_result_message}
                </Text>
              </Group>
            )}
          </Stack>
        </Group>
      </UnstyledButton>
      {children.map((child) => (
        <SubagentNodeRow
          key={child.session_agent_id}
          handle={handle}
          agentId={agentId}
          node={child}
          activeSessionId={activeSessionId}
          activeSessionAgentId={activeSessionAgentId}
          rootSessionAgentId={rootSessionAgentId}
          depth={depth + 1}
          onNavigate={onNavigate}
        />
      ))}
    </Stack>
  );
}

export function SubagentTreePanel({
  handle,
  agentId,
  activeSessionId,
  state,
  onNavigate,
}: SubagentTreePanelProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");

  if (state.type === "LOADING") {
    return (
      <Center h="100%" p="md">
        <Stack align="center" gap="sm">
          <Loader size="sm" />
          <Text size="sm" c="dimmed">
            {t("subagents.loading")}
          </Text>
        </Stack>
      </Center>
    );
  }

  if (state.type === "ERROR") {
    return (
      <Center h="100%" p="md">
        <Stack align="center" gap="sm">
          <ThemeIcon color="red" variant="light" radius="xl">
            <IconAlertCircle size={rem(18)} />
          </ThemeIcon>
          <Text size="sm" c="red" ta="center">
            {state.message}
          </Text>
        </Stack>
      </Center>
    );
  }

  const { tree } = state;
  const childCount = countChildren(tree.nodes);
  const totalCount = countNodes(tree.nodes);

  return (
    <Stack h="100%" gap={0} style={{ overflow: "hidden" }}>
      <Stack gap="xs" p="md">
        <Group gap="xs" justify="space-between" wrap="nowrap">
          <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
            <ThemeIcon variant="light" radius="xl">
              <IconGitBranch size={rem(16)} />
            </ThemeIcon>
            <Box style={{ minWidth: 0 }}>
              <Text fw={700} size="sm">
                {t("subagents.title")}
              </Text>
              <Text size="xs" c="dimmed">
                {t("subagents.summary", { count: childCount })}
              </Text>
            </Box>
          </Group>
          <Badge variant="default" size="sm">
            {t("subagents.total", { count: totalCount })}
          </Badge>
        </Group>
        {childCount === 0 && (
          <Text size="xs" c="dimmed">
            {t("subagents.empty")}
          </Text>
        )}
      </Stack>
      <Divider />
      <ScrollArea flex={1} mih={0}>
        <Stack gap="xs" p="xs">
          {tree.nodes.map((node) => (
            <SubagentNodeRow
              key={node.session_agent_id}
              handle={handle}
              agentId={agentId}
              node={node}
              activeSessionId={activeSessionId}
              activeSessionAgentId={tree.current_session_agent_id}
              rootSessionAgentId={tree.root_session_agent_id}
              depth={0}
              onNavigate={onNavigate}
            />
          ))}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
