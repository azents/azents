"use client";

/** Agent settings page header without session tabs. */

import { ActionIcon, Badge, Box, Group, rem, Stack, Text } from "@mantine/core";
import { IconMenu2 } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { type ReactNode } from "react";
import { formatModelSelectionSummary } from "../model-selection";
import { AgentAvatar } from "./AgentAvatar";
import { useAgentFocusedShellMobileNav } from "./AgentFocusedShell";
import type { AgentResponse } from "@azents/public-client";

interface AgentSettingsHeaderProps {
  agent: AgentResponse;
  controls?: ReactNode;
}

export function AgentSettingsHeader({
  agent,
  controls,
}: AgentSettingsHeaderProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const mobileNav = useAgentFocusedShellMobileNav();
  const modelSummary = formatModelSelectionSummary(agent.model_selection);

  return (
    <Box
      style={{
        borderBottom: "0.0625rem solid var(--mantine-color-default-border)",
        backgroundColor: "var(--mantine-color-body)",
      }}
    >
      <Group
        visibleFrom="lg"
        align="center"
        gap="md"
        px="lg"
        py="sm"
        wrap="nowrap"
      >
        <AgentAvatar
          name={agent.name}
          avatar={agent.avatar ?? null}
          size={40}
        />
        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
          <Group gap="xs" wrap="wrap">
            <Text fw={600} size="md">
              {agent.name}
            </Text>
            <Badge
              size="sm"
              variant="dot"
              color={agent.enabled ? "green" : "gray"}
            >
              {agent.enabled ? t("status.enabled") : t("status.disabled")}
            </Badge>
            <Badge
              size="sm"
              variant="light"
              color={agent.type === "public" ? "blue" : "gray"}
            >
              {agent.type === "public"
                ? t("visibility.public")
                : t("visibility.private")}
            </Badge>
            <Badge size="sm" variant="default">
              {modelSummary}
            </Badge>
          </Group>
          {agent.description && (
            <Text size="xs" c="dimmed" truncate>
              {agent.description}
            </Text>
          )}
        </Stack>
        {controls ? <Box style={{ flexShrink: 0 }}>{controls}</Box> : null}
      </Group>
      <Group
        hiddenFrom="lg"
        align="center"
        gap="xs"
        px="md"
        py="xs"
        wrap="nowrap"
      >
        <ActionIcon
          variant="subtle"
          onClick={mobileNav?.openAgentNavigation}
          aria-label={t("openNavigation")}
        >
          <IconMenu2 size={rem(18)} />
        </ActionIcon>
        <AgentAvatar
          name={agent.name}
          avatar={agent.avatar ?? null}
          size={24}
        />
        <Text fw={600} size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
          {agent.name}
        </Text>
        {controls}
      </Group>
    </Box>
  );
}
