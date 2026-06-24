"use client";

/**
 * Sidebar agent row.
 *
 * Clicking agent enters detail page (/chat tab).
 */

import { Badge, Box, Group, NavLink, Text } from "@mantine/core";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { AgentAvatar } from "./AgentAvatar";
import styles from "./AgentSidebarRow.module.css";
import type { AgentResponse } from "@azents/public-client";

interface AgentSidebarRowProps {
  agent: AgentResponse;
  activeAgentId: string | null;
  basePath: string;
  onNavigate?: () => void;
}

export function AgentSidebarRow({
  agent,
  activeAgentId,
  basePath,
  onNavigate,
}: AgentSidebarRowProps): React.ReactElement {
  const t = useTranslations("workspace.agents");
  const isActive = activeAgentId === agent.id;
  const agentHref = `${basePath}/${agent.id}`;

  return (
    <Box>
      <div className={styles.row}>
        <Box style={{ flex: 1, minWidth: 0 }}>
          <NavLink
            component={Link}
            href={agentHref}
            active={isActive}
            label={
              <Group gap="xs" wrap="nowrap">
                <Text
                  size="sm"
                  fw={isActive ? 600 : 500}
                  c={agent.enabled ? "text" : "dimmed"}
                  style={{
                    flex: 1,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                    whiteSpace: "nowrap",
                  }}
                >
                  {agent.name}
                </Text>
                {!agent.enabled && (
                  <Badge size="xs" variant="default">
                    {t("disabled")}
                  </Badge>
                )}
              </Group>
            }
            leftSection={
              <AgentAvatar
                name={agent.name}
                avatar={agent.avatar ?? null}
                size="sm"
              />
            }
            onClick={onNavigate}
            px="xs"
          />
        </Box>
      </div>
    </Box>
  );
}
