"use client";

/**
 * Agent detail header + tab navigation.
 *
 * Shows Agent context for the focused shell. The desktop Agent navigation lives
 * in the Agent rail; mobile uses this header as the drawer entry point.
 */

import {
  ActionIcon,
  Badge,
  Box,
  Group,
  rem,
  Stack,
  Tabs,
  Text,
} from "@mantine/core";
import {
  IconChartBar,
  IconFolderOpen,
  IconMenu2,
  IconMessageCircle,
  IconSettings,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { type ReactNode, useCallback, useMemo } from "react";
import { formatModelSelectionSummary } from "../model-selection";
import { AgentAvatar } from "./AgentAvatar";
import { useAgentFocusedShellMobileNav } from "./AgentFocusedShell";
import type { AgentResponse } from "@azents/public-client";

/** Extract active tab from current path */
function resolveActiveTab(
  pathname: string,
  basePath: string,
): "chat" | "context" | "settings" {
  if (pathname.startsWith(`${basePath}/context`)) {
    return "context";
  }
  if (pathname.startsWith(`${basePath}/settings`)) {
    return "settings";
  }
  return "chat";
}

interface AgentHeaderProps {
  handle: string;
  agent: AgentResponse;
  onOpenRuntime?: () => void;
  chatControls?: ReactNode;
}

export function AgentHeader({
  handle,
  agent,
  onOpenRuntime,
  chatControls,
}: AgentHeaderProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const router = useRouter();
  const pathname = usePathname();
  const mobileNav = useAgentFocusedShellMobileNav();
  const basePath = `/w/${handle}/agents/${agent.id}`;
  const activeTab = useMemo(
    () => resolveActiveTab(pathname, basePath),
    [pathname, basePath],
  );
  const modelSummary = formatModelSelectionSummary(agent.model_selection);

  const handleTabChange = useCallback(
    (value: string | null): void => {
      if (value === "chat") {
        router.push(`${basePath}/chat`);
      } else if (value === "context") {
        router.push(`${basePath}/context`);
      } else if (value === "settings") {
        router.push(`${basePath}/settings`);
      }
    },
    [router, basePath],
  );

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
        {activeTab === "chat" && chatControls && (
          <Box style={{ flexShrink: 0 }}>{chatControls}</Box>
        )}
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
        {activeTab === "chat" && onOpenRuntime && (
          <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
            {chatControls}
            <ActionIcon
              variant="subtle"
              onClick={onOpenRuntime}
              aria-label="Open agent runtime"
            >
              <IconFolderOpen size="1rem" />
            </ActionIcon>
          </Group>
        )}
      </Group>
      <Tabs
        value={activeTab}
        onChange={handleTabChange}
        variant="default"
        px="sm"
      >
        <Tabs.List>
          <Tabs.Tab value="chat" leftSection={<IconMessageCircle size={14} />}>
            {t("tabs.chat")}
          </Tabs.Tab>
          <Tabs.Tab value="context" leftSection={<IconChartBar size={14} />}>
            {t("tabs.context")}
          </Tabs.Tab>
          <Tabs.Tab value="settings" leftSection={<IconSettings size={14} />}>
            {t("tabs.settings")}
          </Tabs.Tab>
        </Tabs.List>
      </Tabs>
    </Box>
  );
}
