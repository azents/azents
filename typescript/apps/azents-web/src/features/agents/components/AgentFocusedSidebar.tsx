"use client";

/**
 * Agent-focused side navigation.
 *
 * Shows workspace escape hatch, Agent tabs, and the Agent session list in one
 * rail. The same component is reused inside the mobile drawer.
 */
import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  NavLink,
  rem,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconChartBar,
  IconChevronLeft,
  IconMessageCircle,
  IconPlus,
  IconSettings,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { AgentAvatar } from "./AgentAvatar";
import styles from "./AgentFocusedShell.module.css";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

interface AgentFocusedSidebarProps {
  handle: string;
  agent: AgentResponse;
  sessions?: AgentSessionResponse[];
  sessionsLoading?: boolean;
  sessionsError?: string | null;
  activeSessionId?: string | null;
  creatingSession?: boolean;
  onCreateSession?: () => void;
  onNavigate?: () => void;
}

function getActiveSection(pathname: string, basePath: string): string {
  if (pathname.startsWith(`${basePath}/context`)) {
    return "context";
  }
  if (pathname.startsWith(`${basePath}/settings`)) {
    return "settings";
  }
  return "chat";
}

function formatSessionTimestamp(session: AgentSessionResponse): string {
  const formatter = new Intl.DateTimeFormat([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return formatter.format(new Date(session.updated_at));
}

export function AgentFocusedSidebar({
  handle,
  agent,
  sessions = [],
  sessionsLoading = false,
  sessionsError = null,
  activeSessionId = null,
  creatingSession = false,
  onCreateSession,
  onNavigate,
}: AgentFocusedSidebarProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const pathname = usePathname();
  const workspacePath = `/w/${handle}`;
  const basePath = `${workspacePath}/agents/${agent.id}`;
  const activeSection = getActiveSection(pathname, basePath);

  return (
    <Stack h="100%" gap={0} style={{ overflow: "hidden" }}>
      <Box p="md">
        <Button
          component={Link}
          href={workspacePath}
          variant="subtle"
          color="gray"
          size="compact-sm"
          leftSection={<IconChevronLeft size={rem(16)} />}
          onClick={onNavigate}
        >
          {t("backToWorkspace")}
        </Button>
        <Group mt="md" gap="sm" wrap="nowrap" align="center">
          <AgentAvatar
            name={agent.name}
            avatar={agent.avatar ?? null}
            size={40}
            radius="xl"
          />
          <Box style={{ minWidth: 0, flex: 1 }}>
            <Text fw={700} size="sm" truncate>
              {agent.name}
            </Text>
            <Text size="xs" c="dimmed" truncate>
              @{handle}
            </Text>
          </Box>
        </Group>
        {agent.description && (
          <Text mt="xs" size="xs" c="dimmed" lineClamp={2}>
            {agent.description}
          </Text>
        )}
        <Group mt="sm" gap="xs">
          <Badge
            size="xs"
            variant="dot"
            color={agent.enabled ? "green" : "gray"}
          >
            {agent.enabled ? t("status.enabled") : t("status.disabled")}
          </Badge>
          <Badge
            size="xs"
            variant="light"
            color={agent.type === "public" ? "blue" : "gray"}
          >
            {agent.type === "public"
              ? t("visibility.public")
              : t("visibility.private")}
          </Badge>
        </Group>
      </Box>

      <Divider />

      <Box py="xs">
        <NavLink
          component={Link}
          href={`${basePath}/chat`}
          label={t("tabs.chat")}
          leftSection={<IconMessageCircle size={rem(18)} />}
          active={activeSection === "chat"}
          onClick={onNavigate}
          className={styles.sidebarLink}
        />
        <NavLink
          component={Link}
          href={`${basePath}/context`}
          label={t("tabs.context")}
          leftSection={<IconChartBar size={rem(18)} />}
          active={activeSection === "context"}
          onClick={onNavigate}
          className={styles.sidebarLink}
        />
        <NavLink
          component={Link}
          href={`${basePath}/settings`}
          label={t("tabs.settings")}
          leftSection={<IconSettings size={rem(18)} />}
          active={activeSection === "settings"}
          onClick={onNavigate}
          className={styles.sidebarLink}
        />
      </Box>

      <Divider />

      <Group px="md" py="sm" justify="space-between" wrap="nowrap">
        <Text size="xs" fw={700} tt="uppercase" c="dimmed">
          {t("sessions.title")}
        </Text>
        {onCreateSession && (
          <Tooltip label={t("sessions.new")}>
            <ActionIcon
              variant="subtle"
              size="sm"
              aria-label={t("sessions.new")}
              loading={creatingSession}
              onClick={onCreateSession}
            >
              <IconPlus size={rem(16)} />
            </ActionIcon>
          </Tooltip>
        )}
      </Group>

      <ScrollArea flex={1} mih={0}>
        <Stack gap={0} pb="sm">
          {sessionsLoading && (
            <Center py="lg">
              <Loader size="sm" />
            </Center>
          )}
          {sessionsError && (
            <Group px="md" py="sm" gap="xs" wrap="nowrap" c="red">
              <IconAlertCircle size={rem(16)} />
              <Text size="xs">{sessionsError}</Text>
            </Group>
          )}
          {!sessionsLoading && !sessionsError && sessions.length === 0 && (
            <Text px="md" py="sm" size="xs" c="dimmed">
              {t("sessions.empty")}
            </Text>
          )}
          {sessions.map((session) => {
            const href = `${basePath}/sessions/${session.id}`;
            const isPrimary = session.primary_kind === "team_primary";
            return (
              <NavLink
                key={session.id}
                component={Link}
                href={href}
                active={activeSessionId === session.id}
                label={
                  <Group gap="xs" wrap="nowrap">
                    <Text size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
                      {isPrimary
                        ? t("sessions.primary")
                        : t("sessions.session")}
                    </Text>
                    {isPrimary && (
                      <Badge size="xs" variant="light">
                        {t("sessions.primaryBadge")}
                      </Badge>
                    )}
                  </Group>
                }
                description={formatSessionTimestamp(session)}
                onClick={onNavigate}
                className={styles.sessionItem}
              />
            );
          })}
        </Stack>
      </ScrollArea>
    </Stack>
  );
}
