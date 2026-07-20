"use client";

/**
 * Agent-focused side navigation.
 *
 * Shows workspace escape hatch, Agent summary, Agent sessions, and global
 * actions. Session tabs stay in AgentSessionHeader.
 */
import {
  ActionIcon,
  Avatar,
  Badge,
  Box,
  Button,
  Center,
  Collapse,
  Divider,
  Group,
  Loader,
  Menu,
  Modal,
  NavLink,
  rem,
  ScrollArea,
  Stack,
  Text,
  TextInput,
  Tooltip,
  UnstyledButton,
  useMantineColorScheme,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconArchive,
  IconBrightnessAuto,
  IconCheck,
  IconChevronDown,
  IconChevronLeft,
  IconChevronRight,
  IconDots,
  IconExternalLink,
  IconLayoutGrid,
  IconLogout,
  IconMoon,
  IconPencil,
  IconPlus,
  IconRefresh,
  IconSettings,
  IconShieldLock,
  IconSun,
  IconTrash,
  IconUser,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useCallback, useState } from "react";
import { useColorMode } from "@/shared/providers/color-mode";
import { AgentAvatar } from "./AgentAvatar";
import styles from "./AgentFocusedShell.module.css";
import type { ColorModePreference } from "@/shared/lib/color-mode";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

export interface AgentFocusedSidebarUser {
  name: string;
  email: string;
}

interface AgentFocusedSidebarProps {
  handle: string;
  agent: AgentResponse;
  currentUser: AgentFocusedSidebarUser | null;
  adminAccessUrl: string | null;
  loggingOut: boolean;
  onLogout: () => void;
  sessions?: AgentSessionResponse[];
  sessionsLoading?: boolean;
  sessionsError?: string | null;
  archivedSessions?: AgentSessionResponse[];
  archivedSessionsLoading?: boolean;
  archivedSessionsError?: string | null;
  activeSessionId?: string | null;
  creatingSession?: boolean;
  renamingSessionId?: string | null;
  archivingSessionId?: string | null;
  restoringSessionId?: string | null;
  onCreateSession?: () => void;
  onRenameSession?: (sessionId: string, title: string | null) => Promise<void>;
  onArchiveSession?: (sessionId: string) => void;
  onRestoreSession?: (sessionId: string) => void;
  onNavigate?: () => void;
}

function formatTimestamp(value: string): string {
  const formatter = new Intl.DateTimeFormat([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  return formatter.format(new Date(value));
}

function formatSessionTimestamp(session: AgentSessionResponse): string {
  return formatTimestamp(session.updated_at);
}

function getSessionDisplayTitle(
  session: AgentSessionResponse,
  t: ReturnType<typeof useTranslations>,
): string {
  const title = session.title?.trim();
  if (title) {
    return title;
  }
  if (session.primary_kind === "team_primary") {
    return t("sessions.primary");
  }
  return t("sessions.session");
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

function getUserInitial(name: string): string {
  return Array.from(name.trim())[0]?.toLocaleUpperCase() ?? "?";
}

interface ColorModeMenuItemsProps {
  preference: ColorModePreference;
  onSelect: (preference: ColorModePreference) => void;
}

function ColorModeMenuItems({
  preference,
  onSelect,
}: ColorModeMenuItemsProps): React.ReactElement {
  const t = useTranslations("common");

  return (
    <>
      <Menu.Item
        leftSection={<IconSun size={rem(16)} />}
        rightSection={
          preference === "light" ? <IconCheck size={rem(16)} /> : null
        }
        onClick={() => onSelect("light")}
      >
        {t("light")}
      </Menu.Item>
      <Menu.Item
        leftSection={<IconMoon size={rem(16)} />}
        rightSection={
          preference === "dark" ? <IconCheck size={rem(16)} /> : null
        }
        onClick={() => onSelect("dark")}
      >
        {t("dark")}
      </Menu.Item>
      <Menu.Item
        leftSection={<IconBrightnessAuto size={rem(16)} />}
        rightSection={
          preference === "system" ? <IconCheck size={rem(16)} /> : null
        }
        onClick={() => onSelect("system")}
      >
        {t("system")}
      </Menu.Item>
    </>
  );
}

export function AgentFocusedSidebar({
  handle,
  agent,
  currentUser,
  adminAccessUrl,
  loggingOut,
  onLogout,
  sessions = [],
  sessionsLoading = false,
  sessionsError = null,
  archivedSessions = [],
  archivedSessionsLoading = false,
  archivedSessionsError = null,
  activeSessionId = null,
  creatingSession = false,
  renamingSessionId = null,
  archivingSessionId = null,
  restoringSessionId = null,
  onCreateSession,
  onRenameSession,
  onArchiveSession,
  onRestoreSession,
  onNavigate,
}: AgentFocusedSidebarProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const tAppBar = useTranslations("appBar");
  const tCommon = useTranslations("common");
  const tWorkspaceSidebar = useTranslations("workspace.sidebar");
  const pathname = usePathname();
  const workspacePath = `/w/${handle}`;
  const basePath = `${workspacePath}/agents/${agent.id}`;
  const agentHomeHref = `${basePath}/sessions/new`;
  const settingsHref = `${basePath}/settings`;
  const isAgentHomeActive = pathname === basePath || pathname === agentHomeHref;
  const { mode, preference, setColorMode } = useColorMode();
  const { setColorScheme } = useMantineColorScheme();
  const [editingSession, setEditingSession] =
    useState<AgentSessionResponse | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [archiveTarget, setArchiveTarget] =
    useState<AgentSessionResponse | null>(null);
  const [archivedOpened, setArchivedOpened] = useState(false);

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

  const handleLogout = useCallback((): void => {
    onLogout();
  }, [onLogout]);

  const userName =
    currentUser?.name.trim() || currentUser?.email || tAppBar("account");
  const userEmail = currentUser?.email ?? null;

  const handleOpenRename = useCallback(
    (session: AgentSessionResponse): void => {
      setEditingSession(session);
      setEditingTitle(session.title ?? "");
    },
    [],
  );

  const handleCloseRename = useCallback((): void => {
    setEditingSession(null);
    setEditingTitle("");
  }, []);

  const handleSubmitRename = useCallback(async (): Promise<void> => {
    if (!editingSession || !onRenameSession) {
      return;
    }
    const title = editingTitle.trim();
    await onRenameSession(editingSession.id, title);
    handleCloseRename();
  }, [editingSession, editingTitle, handleCloseRename, onRenameSession]);

  const handleClearTitle = useCallback(async (): Promise<void> => {
    if (!editingSession || !onRenameSession) {
      return;
    }
    await onRenameSession(editingSession.id, null);
    handleCloseRename();
  }, [editingSession, handleCloseRename, onRenameSession]);

  const handleConfirmArchive = useCallback((): void => {
    if (archiveTarget === null) {
      return;
    }
    onArchiveSession?.(archiveTarget.id);
    setArchiveTarget(null);
  }, [archiveTarget, onArchiveSession]);

  const renameBusy =
    editingSession !== null && renamingSessionId === editingSession.id;

  return (
    <>
      <Modal
        opened={editingSession !== null}
        onClose={handleCloseRename}
        title={t("sessions.renameTitle")}
        centered
      >
        <Stack gap="md">
          <TextInput
            label={t("sessions.renameLabel")}
            value={editingTitle}
            maxLength={200}
            disabled={renameBusy}
            onChange={(event) => setEditingTitle(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && editingTitle.trim()) {
                event.preventDefault();
                void handleSubmitRename();
              }
            }}
          />
          <Group justify="space-between">
            <Button
              variant="subtle"
              color="red"
              leftSection={<IconTrash size={rem(16)} />}
              disabled={renameBusy || !editingSession?.title}
              onClick={() => void handleClearTitle()}
            >
              {t("sessions.clearTitle")}
            </Button>
            <Group gap="sm">
              <Button variant="default" onClick={handleCloseRename}>
                {t("sessions.cancel")}
              </Button>
              <Button
                loading={renameBusy}
                disabled={!editingTitle.trim()}
                onClick={() => void handleSubmitRename()}
              >
                {t("sessions.save")}
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={archiveTarget !== null}
        onClose={() => setArchiveTarget(null)}
        title={t("sessions.archiveConfirmTitle")}
        centered
      >
        <Stack gap="md">
          <Text size="sm">{t("sessions.archiveConfirmDescription")}</Text>
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setArchiveTarget(null)}>
              {t("sessions.archiveCancel")}
            </Button>
            <Button
              color="red"
              loading={
                archiveTarget !== null &&
                archivingSessionId === archiveTarget.id
              }
              onClick={handleConfirmArchive}
            >
              {t("sessions.archive")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Stack h="100%" gap={0} style={{ overflow: "hidden" }}>
        <Stack p={{ base: "md", lg: "sm" }} className={styles.agentSummary}>
          <Button
            component={Link}
            href={workspacePath}
            variant="subtle"
            color="gray"
            size="compact-sm"
            leftSection={<IconChevronLeft size={rem(16)} />}
            onClick={onNavigate}
            className={styles.backToWorkspaceButton}
          >
            {t("backToWorkspace")}
          </Button>
          <Group gap="xs" wrap="nowrap" align="stretch">
            <UnstyledButton
              component={Link}
              href={agentHomeHref}
              w="100%"
              onClick={onNavigate}
              className={`${styles.agentInfoLink} ${
                isAgentHomeActive ? styles.agentInfoLinkActive : ""
              }`}
            >
              <Group gap="sm" wrap="nowrap" align="center">
                <Box hiddenFrom="lg">
                  <AgentAvatar
                    name={agent.name}
                    avatar={agent.avatar ?? null}
                    size={40}
                    radius="xl"
                  />
                </Box>
                <Box visibleFrom="lg">
                  <AgentAvatar
                    name={agent.name}
                    avatar={agent.avatar ?? null}
                    size={32}
                    radius="xl"
                  />
                </Box>
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
            <Tooltip label={t("tabs.settings")}>
              <ActionIcon
                component={Link}
                href={settingsHref}
                variant="subtle"
                aria-label={t("tabs.settings")}
                onClick={onNavigate}
                className={styles.agentSettingsButton}
              >
                <IconSettings size={rem(18)} />
              </ActionIcon>
            </Tooltip>
          </Group>
          {agent.description && (
            <Text
              mt={{ base: "xs", lg: 0 }}
              size="xs"
              c="dimmed"
              lineClamp={2}
              className={styles.agentDescription}
            >
              {agent.description}
            </Text>
          )}
          <Group mt={{ base: "sm", lg: 0 }} gap="xs">
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
        </Stack>

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
              const running = session.run_state === "running";
              const archiving = archivingSessionId === session.id;
              const showActions =
                onRenameSession != null ||
                (!running && !isPrimary && onArchiveSession != null);
              return (
                <NavLink
                  key={session.id}
                  component={Link}
                  href={href}
                  active={activeSessionId === session.id}
                  label={
                    <Group gap="xs" wrap="nowrap">
                      <Text size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
                        {getSessionDisplayTitle(session, t)}
                      </Text>
                      {running && (
                        <Tooltip label={t("sessions.running")}>
                          <Loader
                            size="xs"
                            aria-label={t("sessions.running")}
                          />
                        </Tooltip>
                      )}
                      {isPrimary && (
                        <Badge size="xs" variant="light">
                          {t("sessions.primaryBadge")}
                        </Badge>
                      )}
                      {showActions && (
                        <Menu
                          shadow="md"
                          width={rem(160)}
                          position="bottom-end"
                        >
                          <Menu.Target>
                            <ActionIcon
                              component="button"
                              type="button"
                              variant="subtle"
                              size="sm"
                              aria-label={t("sessions.actions")}
                              loading={
                                renamingSessionId === session.id || archiving
                              }
                              onClick={(event) => {
                                event.preventDefault();
                                event.stopPropagation();
                              }}
                            >
                              <IconDots size={rem(16)} />
                            </ActionIcon>
                          </Menu.Target>
                          <Menu.Dropdown>
                            {onRenameSession && (
                              <Menu.Item
                                leftSection={<IconPencil size={rem(16)} />}
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  handleOpenRename(session);
                                }}
                              >
                                {t("sessions.rename")}
                              </Menu.Item>
                            )}
                            {!running && !isPrimary && onArchiveSession && (
                              <Menu.Item
                                color="red"
                                leftSection={<IconTrash size={rem(16)} />}
                                onClick={(event) => {
                                  event.preventDefault();
                                  event.stopPropagation();
                                  setArchiveTarget(session);
                                }}
                              >
                                {t("sessions.archive")}
                              </Menu.Item>
                            )}
                          </Menu.Dropdown>
                        </Menu>
                      )}
                    </Group>
                  }
                  description={formatSessionTimestamp(session)}
                  onClick={onNavigate}
                  className={styles.sessionItem}
                />
              );
            })}

            <Divider my="xs" />
            <UnstyledButton
              px="md"
              py="xs"
              onClick={() => setArchivedOpened((opened) => !opened)}
              aria-expanded={archivedOpened}
              className={styles.archivedSectionToggle}
            >
              <Group justify="space-between" wrap="nowrap">
                <Group gap="xs" wrap="nowrap">
                  <IconArchive size={rem(15)} />
                  <Text size="xs" fw={700} tt="uppercase" c="dimmed">
                    {t("sessions.archivedTitle")}
                  </Text>
                  {!archivedSessionsLoading && !archivedSessionsError && (
                    <Badge size="xs" variant="light" color="gray">
                      {archivedSessions.length}
                    </Badge>
                  )}
                </Group>
                <IconChevronDown
                  size={rem(15)}
                  style={{
                    transform: archivedOpened ? "rotate(180deg)" : "none",
                    transition: "transform 150ms ease",
                  }}
                />
              </Group>
            </UnstyledButton>
            <Collapse expanded={archivedOpened}>
              <Stack gap={0} pb="xs">
                {archivedSessionsLoading && (
                  <Center py="md">
                    <Loader size="sm" />
                  </Center>
                )}
                {archivedSessionsError && (
                  <Group px="md" py="sm" gap="xs" wrap="nowrap" c="red">
                    <IconAlertCircle size={rem(16)} />
                    <Text size="xs">{archivedSessionsError}</Text>
                  </Group>
                )}
                {!archivedSessionsLoading &&
                  !archivedSessionsError &&
                  archivedSessions.length === 0 && (
                    <Text px="md" py="sm" size="xs" c="dimmed">
                      {t("sessions.archivedEmpty")}
                    </Text>
                  )}
                {archivedSessions.map((session) => {
                  const restoring = restoringSessionId === session.id;
                  const archivedAt = session.archived_at ?? session.updated_at;
                  const retentionLabel =
                    session.archive_retention_days_snapshot === null
                      ? t("sessions.retentionSnapshotUnlimited")
                      : t("sessions.retentionSnapshotDays", {
                          days: session.archive_retention_days_snapshot,
                        });
                  const purgeLabel = session.purge_after
                    ? t("sessions.purgeScheduled", {
                        date: formatTimestamp(session.purge_after),
                      })
                    : t("sessions.purgeUnscheduled");
                  return (
                    <Box
                      key={session.id}
                      px="md"
                      py="sm"
                      className={styles.archivedSessionItem}
                    >
                      <Group gap="xs" wrap="nowrap" align="flex-start">
                        <Stack gap={2} style={{ flex: 1, minWidth: 0 }}>
                          <Text size="sm" truncate>
                            {getSessionDisplayTitle(session, t)}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {t("sessions.archivedAt", {
                              date: formatTimestamp(archivedAt),
                            })}
                          </Text>
                          <Text size="xs" c="dimmed">
                            {retentionLabel} · {purgeLabel}
                          </Text>
                        </Stack>
                        {onRestoreSession && (
                          <Tooltip label={t("sessions.restore")}>
                            <ActionIcon
                              variant="subtle"
                              size="sm"
                              aria-label={t("sessions.restore")}
                              loading={restoring}
                              onClick={() => onRestoreSession(session.id)}
                            >
                              <IconRefresh size={rem(16)} />
                            </ActionIcon>
                          </Tooltip>
                        )}
                      </Group>
                    </Box>
                  );
                })}
              </Stack>
            </Collapse>
          </Stack>
        </ScrollArea>

        <Box visibleFrom="lg">
          <Divider />
          <Box p="xs">
            <Menu shadow="md" width={rem(272)} position="top-start" offset={8}>
              <Menu.Target>
                <UnstyledButton className={styles.userMenuTrigger}>
                  <Group gap="sm" wrap="nowrap">
                    <Avatar size={32} radius="xl" color="orange">
                      {getUserInitial(userName)}
                    </Avatar>
                    <Box style={{ flex: 1, minWidth: 0 }}>
                      <Text size="sm" fw={600} truncate>
                        {userName}
                      </Text>
                      {userEmail && (
                        <Text size="xs" c="dimmed" truncate>
                          {userEmail}
                        </Text>
                      )}
                    </Box>
                    <IconChevronRight size={rem(16)} />
                  </Group>
                </UnstyledButton>
              </Menu.Target>
              <Menu.Dropdown>
                <Box px="sm" py="xs">
                  <Text size="sm" fw={600} truncate>
                    {userName}
                  </Text>
                  {userEmail && (
                    <Text size="xs" c="dimmed" truncate>
                      {userEmail}
                    </Text>
                  )}
                </Box>
                <Divider />
                <Menu.Item
                  component={Link}
                  href="/workspaces"
                  leftSection={<IconLayoutGrid size={rem(16)} />}
                  onClick={onNavigate}
                >
                  {tWorkspaceSidebar("workspaces")}
                </Menu.Item>
                <Menu.Item
                  component={Link}
                  href="/account"
                  leftSection={<IconUser size={rem(16)} />}
                  onClick={onNavigate}
                >
                  {tAppBar("account")}
                </Menu.Item>
                {adminAccessUrl && (
                  <Menu.Item
                    component="a"
                    href={adminAccessUrl}
                    target="_blank"
                    rel="noopener noreferrer"
                    leftSection={<IconShieldLock size={rem(16)} />}
                    rightSection={<IconExternalLink size={rem(14)} />}
                    onClick={onNavigate}
                  >
                    {tAppBar("admin")}
                  </Menu.Item>
                )}
                <Menu.Sub>
                  <Menu.Sub.Target>
                    <Menu.Sub.Item
                      leftSection={getColorModeIcon(preference, mode)}
                      rightSection={
                        <Text size="xs" c="dimmed">
                          {tCommon(preference)}
                        </Text>
                      }
                    >
                      {tCommon("colorMode")}
                    </Menu.Sub.Item>
                  </Menu.Sub.Target>
                  <Menu.Sub.Dropdown w={rem(180)}>
                    <ColorModeMenuItems
                      preference={preference}
                      onSelect={handleSelectColorMode}
                    />
                  </Menu.Sub.Dropdown>
                </Menu.Sub>
                <Menu.Divider />
                <Menu.Item
                  color="red"
                  leftSection={<IconLogout size={rem(16)} />}
                  disabled={loggingOut}
                  onClick={handleLogout}
                >
                  {tAppBar("logout")}
                </Menu.Item>
              </Menu.Dropdown>
            </Menu>
          </Box>
        </Box>

        <Box hiddenFrom="lg">
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
            {adminAccessUrl && (
              <NavLink
                component="a"
                href={adminAccessUrl}
                target="_blank"
                rel="noopener noreferrer"
                label={tAppBar("admin")}
                leftSection={<IconShieldLock size={rem(18)} />}
                rightSection={<IconExternalLink size={rem(16)} />}
                onClick={onNavigate}
              />
            )}
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
                <ColorModeMenuItems
                  preference={preference}
                  onSelect={handleSelectColorMode}
                />
              </Menu.Dropdown>
            </Menu>
            <NavLink
              component="button"
              type="button"
              label={tAppBar("logout")}
              leftSection={<IconLogout size={rem(18)} />}
              disabled={loggingOut}
              onClick={handleLogout}
            />
          </Stack>
        </Box>
      </Stack>
    </>
  );
}
