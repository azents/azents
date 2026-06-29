"use client";

/**
 * Home subagent list row.
 *
 * Subagent cannot chat independently — list layout shows "Subagent" badge +
 * description only. Parent agent link / call metrics have no backend telemetry,
 * so omitted in first pass (deferred).
 */

import { Badge, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentAvatar } from "@/features/agents/components/AgentAvatar";
import styles from "./WorkspaceHome.module.css";
import type { EnrichedAgent } from "../types";

interface SubagentTeamRowProps {
  handle: string;
  subagent: EnrichedAgent;
}

export function SubagentTeamRow({
  handle,
  subagent,
}: SubagentTeamRowProps): React.ReactElement {
  const tHome = useTranslations("workspace.home.card");
  const href = `/w/${handle}/agents/${subagent.id}/sessions/new`;
  return (
    <UnstyledButton
      component={Link}
      href={href}
      p="sm"
      className={styles.subagentRow}
      style={{
        opacity: subagent.enabled ? 1 : 0.55,
      }}
    >
      <Group align="center" gap="md" wrap="nowrap">
        <AgentAvatar
          name={subagent.name}
          avatar={subagent.avatar}
          size={40}
          radius="md"
        />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="nowrap">
            <Text fw={600} truncate>
              {subagent.name}
            </Text>
            <Badge size="xs" color="violet" variant="light">
              {tHome("subagentBadge")}
            </Badge>
            {!subagent.enabled && (
              <Badge size="xs" color="gray" variant="outline">
                {tHome("disabled")}
              </Badge>
            )}
          </Group>
          <Text size="xs" className={styles.rowDescription} truncate>
            {subagent.description || tHome("noDescription")}
          </Text>
        </Stack>
      </Group>
    </UnstyledButton>
  );
}
