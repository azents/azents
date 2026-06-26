"use client";

/**
 * Agent-focused side navigation.
 *
 * Shows workspace escape hatch, Agent summary, Agent sessions, and global
 * actions. Agent section tabs stay in AgentHeader.
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
  Menu,
  NavLink,
  rem,
  ScrollArea,
  Stack,
  Text,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconBrightnessAuto,
  IconCheck,
  IconChevronLeft,
  IconLayoutGrid,
  IconLogout,
  IconMoon,
  IconPlus,
  IconSun,
  IconUser,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useCallback } from "react";
import { useColorMode } from "@/shared/providers/color-mode";
import { trpc } from "@/trpc/client";
import { AgentAvatar } from "./AgentAvatar";
import styles from "./AgentFocusedShell.module.css";
import type { ColorModePreference } from "@/shared/lib/color-mode";
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

function formatSessionTimestamp(session: AgentSessionResponse): string {
  const formatter = new Intl.DateTimeFormat([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return formatter.format(new Date(session.updated_at));
}

function getColorModeIcon(
  preference: ColorModePreference,
  resolvedMode: "light" | "dark",
): React.ReactElement {
  if (preference === "system") {
    return <IconBrightnessAuto size={rem(16)} />;
  }
  return resolvedMode === "dark" ? (
    <IconMoon size={rem(16)} />
  ) : (
    <IconSun size={rem(16)} />
  );
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
  const tAppBar = useTranslations("appBar");
  const tCommon = useTranslations("common");
  const tWorkspaceSidebar = useTranslations("workspace.sidebar");
  const router = useRouter();
  const pathname = usePathname();
  const workspacePath = `/w/${handle}`;
  const basePath = `${workspacePath}/agents/${agent.id}`;
  const settingsHref = activeSessionId
    ? `${basePath}/settings?sessionId=${encodeURIComponent(activeSessionId)}`
    : `${basePath}/settings`;
  const isAgentSettingsActive = pathname.startsWith(`${basePath}/settings`);
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();

  const logoutMutation = trpc.auth.logout.useMutation({
    onSuccess: () => {
      onNavigate?.();
      router.push("/");
    },
  });

  const handleLogout = useCallback((): void => {
    logoutMutation.mutate();
  }, [logoutMutation]);

  const handleSelectColorMode = useCallback(
    (newPreference: ColorModePreference): void => {
      setColorMode(newPreference);
      if (newPreference === "system") {
        setColorScheme("auto");
      } else {
        setColorScheme(newPreference);
      }
    },
    [setColorMode, setColorScheme],
  );

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
        <UnstyledButton
          component={Link}
          href={settingsHref}
          mt="md"
          w="100%"
          onClick={onNavigate}
          className={`${styles.agentInfoLink} ${
            isAgentSettingsActive ? styles.agentInfoLinkActive : ""
          }`}
        >
          <Group gap="sm" wrap="nowrap" align="center">
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
        </UnstyledButton>
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
                    <Text size="sm" truncate style={{ minWidth: 0 }}>
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
                rightSection={
                  session.run_state === "running" ? (
                    <Tooltip label={t("sessions.running")}>
                      <Loader size="xs" aria-label={t("sessions.running")} />
                    </Tooltip>
                  ) : null
                }
                description={formatSessionTimestamp(session)}
                onClick={onNavigate}
                className={styles.sessionItem}
              />
            );
          })}
        </Stack>
      </ScrollArea>

      <Divider />

      <Stack gap={0} p="xs">
        <NavLink
          component={Link}
          href="/workspaces"
          label={tWorkspaceSidebar("workspaces")}
          leftSection={<IconLayoutGrid size={rem(18)} />}
          onClick={onNavigate}
        />
        <NavLink
          component={Link}
          href="/account"
          label={tAppBar("account")}
          leftSection={<IconUser size={rem(18)} />}
          onClick={onNavigate}
        />
        <Menu shadow="md" width={rem(180)} position="top-start">
          <Menu.Target>
            <Button
              variant="subtle"
              color="gray"
              justify="flex-start"
              fullWidth
              leftSection={getColorModeIcon(preference, mode)}
              styles={{ inner: { justifyContent: "flex-start" } }}
            >
              {tCommon("colorMode")}
            </Button>
          </Menu.Target>
          <Menu.Dropdown>
            <Menu.Item
              leftSection={<IconSun size={rem(16)} />}
              rightSection={
                preference === "light" ? <IconCheck size={rem(16)} /> : null
              }
              onClick={() => handleSelectColorMode("light")}
            >
              {tCommon("light")}
            </Menu.Item>
            <Menu.Item
              leftSection={<IconMoon size={rem(16)} />}
              rightSection={
                preference === "dark" ? <IconCheck size={rem(16)} /> : null
              }
              onClick={() => handleSelectColorMode("dark")}
            >
              {tCommon("dark")}
            </Menu.Item>
            <Menu.Item
              leftSection={<IconBrightnessAuto size={rem(16)} />}
              rightSection={
                preference === "system" ? <IconCheck size={rem(16)} /> : null
              }
              onClick={() => handleSelectColorMode("system")}
            >
              {tCommon("system")}
            </Menu.Item>
          </Menu.Dropdown>
        </Menu>
        <NavLink
          component="button"
          type="button"
          label={tAppBar("logout")}
          leftSection={<IconLogout size={rem(18)} />}
          disabled={logoutMutation.isPending}
          onClick={handleLogout}
        />
      </Stack>
    </Stack>
  );
}
