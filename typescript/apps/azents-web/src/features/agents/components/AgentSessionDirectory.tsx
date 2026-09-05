"use client";

import {
  ActionIcon,
  Alert,
  Badge,
  Box,
  Button,
  Center,
  Divider,
  Group,
  Loader,
  Menu,
  Modal,
  NavLink,
  Pagination,
  rem,
  ScrollArea,
  Stack,
  Tabs,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import {
  IconAlertCircle,
  IconArchive,
  IconDots,
  IconPencil,
  IconPin,
  IconPlus,
  IconRefresh,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useState } from "react";
import { AgentSettingsHeader } from "@/shared/agent-session/AgentSettingsHeader";
import { formatLocalizedDate } from "@/shared/lib/date-format";
import { useLocale } from "@/shared/providers/locale";
import { isAutoArchiveDueSoon } from "../auto-archive-urgency";
import type { AgentSessionDirectoryStatus } from "../containers/useAgentSessionDirectoryContainer";
import type { SupportedLocale } from "@/shared/lib/locale";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

export interface AgentSessionDirectoryProps {
  handle: string;
  agent: AgentResponse;
  status: AgentSessionDirectoryStatus;
  page: number;
  pageSize: number;
  sessions: AgentSessionResponse[];
  totalCount: number;
  currentArchiveRetentionDays: number | null;
  loading: boolean;
  error: string | null;
  actionError: string | null;
  renamingSessionId: string | null;
  archivingSessionId: string | null;
  pinningSessionId: string | null;
  restoringSessionId: string | null;
  onStatusChange: (status: AgentSessionDirectoryStatus) => void;
  onPageChange: (page: number) => void;
  onCreateSession: () => void;
  onRenameSession: (sessionId: string, title: string | null) => Promise<void>;
  onArchiveSession: (sessionId: string) => void;
  onSetSessionPinned: (sessionId: string, pinned: boolean) => void;
  onRestoreSession: (sessionId: string) => void;
}

function formatTimestamp(value: string, locale: SupportedLocale): string {
  return formatLocalizedDate(new Date(value), locale, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
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

function isDirectoryStatus(
  value: string,
): value is AgentSessionDirectoryStatus {
  return value === "active" || value === "archived";
}

export function AgentSessionDirectory({
  handle,
  agent,
  status,
  page,
  pageSize,
  sessions,
  totalCount,
  currentArchiveRetentionDays,
  loading,
  error,
  actionError,
  renamingSessionId,
  archivingSessionId,
  pinningSessionId,
  restoringSessionId,
  onStatusChange,
  onPageChange,
  onCreateSession,
  onRenameSession,
  onArchiveSession,
  onSetSessionPinned,
  onRestoreSession,
}: AgentSessionDirectoryProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const { locale } = useLocale();
  const [editingSession, setEditingSession] =
    useState<AgentSessionResponse | null>(null);
  const [editingTitle, setEditingTitle] = useState("");
  const [archiveTarget, setArchiveTarget] =
    useState<AgentSessionResponse | null>(null);
  const basePath = `/w/${handle}/agents/${agent.id}`;
  const totalPages = Math.max(1, Math.ceil(totalCount / pageSize));
  const isArchived = status === "archived";
  const renameBusy =
    editingSession !== null && renamingSessionId === editingSession.id;

  const handleOpenRename = (session: AgentSessionResponse): void => {
    setEditingSession(session);
    setEditingTitle(session.title ?? "");
  };

  const handleCloseRename = (): void => {
    setEditingSession(null);
    setEditingTitle("");
  };

  const handleSubmitRename = async (): Promise<void> => {
    if (!editingSession || !editingTitle.trim()) {
      return;
    }
    await onRenameSession(editingSession.id, editingTitle.trim());
    handleCloseRename();
  };

  const handleClearTitle = async (): Promise<void> => {
    if (!editingSession) {
      return;
    }
    await onRenameSession(editingSession.id, null);
    handleCloseRename();
  };

  const handleConfirmArchive = (): void => {
    if (!archiveTarget) {
      return;
    }
    onArchiveSession(archiveTarget.id);
    setArchiveTarget(null);
  };

  const renderActiveSession = (
    session: AgentSessionResponse,
  ): React.ReactElement => {
    const href = `${basePath}/sessions/${session.id}`;
    const isPrimary = session.primary_kind === "team_primary";
    const running = session.run_state === "running";
    const showUnreadIndicator =
      !running && session.unread_terminal_run_id !== null;
    const autoArchiveDueSoon = isAutoArchiveDueSoon(
      session.auto_archive_after,
      agent.auto_archive_ttl_days,
      Date.now(),
    );
    const pinning = pinningSessionId === session.id;
    const archiving = archivingSessionId === session.id;

    return (
      <NavLink
        key={session.id}
        component={Link}
        href={href}
        px={0}
        py="sm"
        label={
          <Group gap="xs" wrap="nowrap">
            <Text size="sm" truncate style={{ flex: 1, minWidth: 0 }}>
              {getSessionDisplayTitle(session, t)}
            </Text>
            {autoArchiveDueSoon && session.auto_archive_after && (
              <Tooltip
                label={t("sessions.autoArchiveScheduled", {
                  date: formatTimestamp(session.auto_archive_after, locale),
                })}
              >
                <Badge size="xs" variant="light" color="orange">
                  {t("sessions.autoArchiveDueSoonBadge")}
                </Badge>
              </Tooltip>
            )}
            {showUnreadIndicator && (
              <Box
                component="span"
                w={rem(8)}
                h={rem(8)}
                bg="var(--mantine-primary-color-filled)"
                style={{ borderRadius: "50%", flexShrink: 0 }}
                role="img"
                aria-label={t("sessions.unreadTerminalRun")}
              />
            )}
            {running && (
              <Tooltip label={t("sessions.running")}>
                <Loader size="xs" aria-label={t("sessions.running")} />
              </Tooltip>
            )}
            {isPrimary && (
              <Badge size="xs" variant="light">
                {t("sessions.primaryBadge")}
              </Badge>
            )}
            {session.pinned && (
              <Tooltip label={t("sessions.pinned")}>
                <IconPin size={rem(16)} aria-label={t("sessions.pinned")} />
              </Tooltip>
            )}
            <Menu shadow="md" width={rem(160)} position="bottom-end">
              <Menu.Target>
                <ActionIcon
                  component="button"
                  type="button"
                  variant="subtle"
                  size="sm"
                  aria-label={t("sessions.actions")}
                  loading={
                    renamingSessionId === session.id || archiving || pinning
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
                {!isPrimary && (
                  <Menu.Item
                    leftSection={<IconPin size={rem(16)} />}
                    disabled={pinning}
                    onClick={(event) => {
                      event.preventDefault();
                      event.stopPropagation();
                      onSetSessionPinned(session.id, !session.pinned);
                    }}
                  >
                    {session.pinned ? t("sessions.unpin") : t("sessions.pin")}
                  </Menu.Item>
                )}
                {!running && !isPrimary && (
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
          </Group>
        }
        description={formatTimestamp(session.updated_at, locale)}
      />
    );
  };

  const renderArchivedSession = (
    session: AgentSessionResponse,
  ): React.ReactElement => {
    const href = `${basePath}/sessions/${session.id}`;
    const archivedAt = session.archived_at ?? session.updated_at;
    const retentionLabel =
      session.archive_retention_days_snapshot === null
        ? t("sessions.retentionSnapshotUnlimited")
        : t("sessions.retentionSnapshotDays", {
            days: session.archive_retention_days_snapshot,
          });
    const purgeLabel = session.purge_after
      ? t("sessions.purgeScheduled", {
          date: formatTimestamp(session.purge_after, locale),
        })
      : t("sessions.purgeUnscheduled");
    const restoring = restoringSessionId === session.id;

    return (
      <Group key={session.id} gap="xs" py="sm" wrap="nowrap">
        <NavLink
          component={Link}
          href={href}
          style={{ flex: 1, minWidth: 0 }}
          label={
            <Text size="sm" truncate>
              {getSessionDisplayTitle(session, t)}
            </Text>
          }
          description={
            <Stack gap={2}>
              <Text size="xs" c="dimmed">
                {t("sessions.archivedAt", {
                  date: formatTimestamp(archivedAt, locale),
                })}
              </Text>
              <Text size="xs" c="dimmed">
                {retentionLabel} · {purgeLabel}
              </Text>
            </Stack>
          }
        />
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
      </Group>
    );
  };

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

      <Box
        h="100%"
        mih={0}
        style={{ display: "flex", flexDirection: "column" }}
      >
        <AgentSettingsHeader
          agent={agent}
          controls={
            <Button
              size="compact-sm"
              leftSection={<IconPlus size={rem(16)} />}
              onClick={onCreateSession}
            >
              {t("sessions.new")}
            </Button>
          }
        />
        <ScrollArea flex={1} mih={0} type="auto">
          <Stack
            gap="md"
            p={{ base: "md", sm: "lg" }}
            maw={rem(960)}
            mx="auto"
            w="100%"
          >
            <Text fw={600} size="lg">
              {t("sessions.title")}
            </Text>

            <Tabs
              value={status}
              onChange={(value) => {
                if (value && isDirectoryStatus(value)) {
                  onStatusChange(value);
                }
              }}
            >
              <Tabs.List grow>
                <Tabs.Tab value="active">{t("sessions.active")}</Tabs.Tab>
                <Tabs.Tab value="archived">{t("sessions.archived")}</Tabs.Tab>
              </Tabs.List>
            </Tabs>

            <Group justify="space-between" wrap="wrap" gap="xs">
              <Group gap="xs">
                <Text fw={600}>
                  {isArchived ? t("sessions.archived") : t("sessions.active")}
                </Text>
                <Badge variant="light">{totalCount}</Badge>
              </Group>
              {isArchived && (
                <Text size="sm" c="dimmed">
                  {currentArchiveRetentionDays === null
                    ? t("sessions.currentRetentionUnlimited")
                    : t("sessions.currentRetentionDays", {
                        days: currentArchiveRetentionDays,
                      })}
                </Text>
              )}
            </Group>

            {loading && (
              <Center py="xl">
                <Loader />
              </Center>
            )}
            {error && (
              <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
                {error}
              </Alert>
            )}
            {actionError && (
              <Alert color="red" icon={<IconAlertCircle size={rem(18)} />}>
                {actionError}
              </Alert>
            )}
            {!loading && !error && sessions.length === 0 && (
              <Stack align="center" gap="xs" py="xl">
                <IconArchive size={rem(28)} opacity={0.45} />
                <Text c="dimmed">
                  {isArchived
                    ? t("sessions.archivedEmpty")
                    : t("sessions.empty")}
                </Text>
              </Stack>
            )}
            {!loading && !error && sessions.length > 0 && (
              <Box
                style={{
                  borderBottom: `${rem(1)} solid var(--mantine-color-default-border)`,
                  borderTop: `${rem(1)} solid var(--mantine-color-default-border)`,
                }}
              >
                {sessions.map((session, index) => (
                  <Box key={session.id}>
                    {index > 0 && <Divider />}
                    {isArchived
                      ? renderArchivedSession(session)
                      : renderActiveSession(session)}
                  </Box>
                ))}
              </Box>
            )}

            <Stack align="center" gap="xs">
              <Pagination
                value={page}
                total={totalPages}
                disabled={loading}
                onChange={onPageChange}
              />
              <Text size="sm" c="dimmed" aria-live="polite">
                {t("sessions.pageStatus", { page, pages: totalPages })}
              </Text>
            </Stack>
          </Stack>
        </ScrollArea>
      </Box>
    </>
  );
}
