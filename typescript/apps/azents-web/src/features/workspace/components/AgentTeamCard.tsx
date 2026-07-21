"use client";

/** Home primary agent card — one cell in 3-col grid. */

import { Badge, Card, Group, Stack, Text } from "@mantine/core";
import { IconClock } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentAvatar } from "@/features/agents/components/AgentAvatar";
import { formatLocalizedDate } from "@/shared/lib/date-format";
import { useLocale } from "@/shared/providers/locale";
import styles from "./WorkspaceHome.module.css";
import type { EnrichedAgent } from "../types";
import type { SupportedLocale } from "@/shared/lib/locale";

type ChatTranslator = ReturnType<typeof useTranslations<"chat">>;

function formatRelative(
  iso: string,
  t: ChatTranslator,
  locale: SupportedLocale,
): string {
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
  return formatLocalizedDate(new Date(iso), locale);
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
  const { locale } = useLocale();
  const href = `/w/${handle}/agents/${agent.id}/sessions/new`;

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
              {agent.modelSummary}
            </Text>
          </Group>
        </Stack>
      </Group>

      <Text
        size="sm"
        className={styles.rowDescription}
        lineClamp={2}
        style={{ minHeight: "2.2em" }}
      >
        {agent.description || tHome("noDescription")}
      </Text>

      <Group gap={6} mt="auto">
        <IconClock size={14} />
        <Text size="xs" c="dimmed">
          {formatRelative(agent.lastActiveAt, t, locale)}
        </Text>
      </Group>
    </Card>
  );
}
