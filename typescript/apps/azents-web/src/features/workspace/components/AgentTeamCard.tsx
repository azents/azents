"use client";

/**
 * Home primary agent card — one cell in 3-col grid.
 *
 * Avatar + name + enabled state + provider + description (2-line clamp) + last modified time.
 * Busy pulse / owner / toolkit badges omitted first due to no current data.
 */

import { Badge, Card, Group, Stack, Text } from "@mantine/core";
import { IconClock } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentAvatar } from "@/features/agents/components/AgentAvatar";
import styles from "./WorkspaceHome.module.css";
import type { EnrichedAgent } from "../types";

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

/** Relative time — uses justNow/minutesAgo/hoursAgo/daysAgo keys in chat namespace */
function formatRelative(iso: string, t: ChatTranslator): string {
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.floor(diff / 60_000);
  if (minutes < 1) {
    return t("justNow");
  }
  if (minutes < 60) {
    return t("minutesAgo", { count: minutes });
  }
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    return t("hoursAgo", { count: hours });
  }
  const days = Math.floor(hours / 24);
  if (days < 30) {
    return t("daysAgo", { count: days });
  }
  return new Date(iso).toLocaleDateString();
}

interface AgentTeamCardProps {
  handle: string;
  agent: EnrichedAgent;
}

export function AgentTeamCard({
  handle,
  agent,
}: AgentTeamCardProps): React.ReactElement {
  const t = useTranslations("chat");
  const tHome = useTranslations("workspace.home.card");

  const modelLabel = agent.modelSummary;

  const href = `/w/${handle}/agents/${agent.id}/chat`;

  return (
    <Card
      component={Link}
      href={href}
      withBorder
      padding="md"
      radius="md"
      className={styles.teamCard}
      style={{
        opacity: agent.enabled ? 1 : 0.55,
        display: "flex",
        flexDirection: "column",
        gap: "var(--mantine-spacing-sm)",
        height: "100%",
        cursor: "pointer",
        textDecoration: "none",
        color: "inherit",
      }}
    >
      {/* Header: avatar + name + status */}
      <Group align="flex-start" gap="sm" wrap="nowrap">
        <AgentAvatar
          name={agent.name}
          avatar={agent.avatar}
          size={52}
          radius="md"
        />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Text fw={600} truncate>
            {agent.name}
          </Text>
          <Group gap={6} wrap="nowrap">
            <Badge
              size="xs"
              variant="dot"
              color={agent.enabled ? "green" : "gray"}
            >
              {agent.enabled ? tHome("enabled") : tHome("disabled")}
            </Badge>
            <Text size="xs" c="dimmed" truncate>
              {modelLabel}
            </Text>
          </Group>
        </Stack>
      </Group>

      {/* Description */}
      <Text
        size="sm"
        className={styles.rowDescription}
        lineClamp={2}
        style={{ minHeight: "2.2em" }}
      >
        {agent.description || tHome("noDescription")}
      </Text>

      {/* Role badge (subagent only, reserved) */}
      {agent.role === "subagent" && (
        <Badge size="xs" color="violet" variant="light">
          {tHome("subagentBadge")}
        </Badge>
      )}

      {/* Footer: last updated */}
      <Group gap="xs" wrap="nowrap" pt="xs" className={styles.teamCardFooter}>
        <IconClock size={12} />
        <Text size="xs" c="dimmed" truncate>
          {formatRelative(agent.lastActiveAt, t)}
        </Text>
      </Group>
    </Card>
  );
}
