"use client";

/**
 * Agent session header + tab navigation.
 *
 * The Chat/Context tabs are session-scoped controls, so this header is rendered
 * only from concrete Agent session routes.
 */

import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Group,
  Modal,
  rem,
  Stack,
  Tabs,
  Text,
  TextInput,
} from "@mantine/core";
import {
  IconChartBar,
  IconFolderOpen,
  IconGitBranch,
  IconMenu2,
  IconMessageCircle,
  IconPencil,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { useRouter, useSearchParams } from "next/navigation";
import { type ReactNode, useCallback, useMemo, useState } from "react";
import { trpc } from "@/trpc/client";
import { formatModelSelectionSummary } from "../model-selection";
import { AgentAvatar } from "./AgentAvatar";
import { useAgentFocusedShellMobileNav } from "./AgentFocusedShell";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

function isContextPage(value: string | null): boolean {
  return (
    value === "context" || value === "system-prompt" || value === "raw-events"
  );
}

function resolveActiveTab(
  page: string | null,
): "chat" | "context" | "subagents" {
  if (isContextPage(page)) {
    return "context";
  }
  if (page === "subagents") {
    return "subagents";
  }
  return "chat";
}

function getSessionDisplayTitle(
  session: AgentSessionResponse | null,
  t: ReturnType<typeof useTranslations>,
): string {
  const title = session?.title?.trim();
  if (title) {
    return title;
  }
  if (session?.primary_kind === "team_primary") {
    return t("sessions.primary");
  }
  return t("sessions.session");
}

interface AgentSessionHeaderProps {
  handle: string;
  agent: AgentResponse;
  sessionId: string;
  session?: AgentSessionResponse;
  onSessionTitleChange?: (session: AgentSessionResponse) => void;
  onOpenRuntime?: () => void;
  chatControls?: ReactNode;
}

export function AgentSessionHeader({
  handle,
  agent,
  sessionId,
  session: initialSession,
  onSessionTitleChange,
  onOpenRuntime,
  chatControls,
}: AgentSessionHeaderProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const router = useRouter();
  const searchParams = useSearchParams();
  const mobileNav = useAgentFocusedShellMobileNav();
  const utils = trpc.useUtils();
  const sessionQuery = trpc.chat.getAgentSession.useQuery(
    {
      agentId: agent.id,
      sessionId,
    },
    {
      enabled: typeof initialSession === "undefined",
      initialData: initialSession,
    },
  );
  const updateTitleMutation = trpc.chat.updateAgentSessionTitle.useMutation();
  const session = initialSession ?? sessionQuery.data ?? null;
  const sessionTitle = getSessionDisplayTitle(session, t);
  const [editingOpened, setEditingOpened] = useState(false);
  const [editingTitle, setEditingTitle] = useState("");
  const basePath = `/w/${handle}/agents/${agent.id}`;
  const activeTab = useMemo(
    () => resolveActiveTab(searchParams.get("page")),
    [searchParams],
  );
  const modelSummary = formatModelSelectionSummary(agent.model_selection);

  const handleOpenRename = useCallback((): void => {
    setEditingTitle(session?.title ?? "");
    setEditingOpened(true);
  }, [session?.title]);

  const handleCloseRename = useCallback((): void => {
    setEditingOpened(false);
    setEditingTitle("");
  }, []);

  const handleSubmitRename = useCallback(async (): Promise<void> => {
    const title = editingTitle.trim();
    if (!title) {
      return;
    }
    const updatedSession = await updateTitleMutation.mutateAsync({
      agentId: agent.id,
      sessionId,
      title,
    });
    onSessionTitleChange?.(updatedSession);
    await Promise.all([
      utils.chat.getAgentSession.invalidate({ agentId: agent.id, sessionId }),
      utils.chat.listAgentSessions.invalidate({ agentId: agent.id }),
    ]);
    handleCloseRename();
  }, [
    agent.id,
    editingTitle,
    handleCloseRename,
    onSessionTitleChange,
    sessionId,
    updateTitleMutation,
    utils.chat.getAgentSession,
    utils.chat.listAgentSessions,
  ]);

  const handleClearTitle = useCallback(async (): Promise<void> => {
    const updatedSession = await updateTitleMutation.mutateAsync({
      agentId: agent.id,
      sessionId,
      title: null,
    });
    onSessionTitleChange?.(updatedSession);
    await Promise.all([
      utils.chat.getAgentSession.invalidate({ agentId: agent.id, sessionId }),
      utils.chat.listAgentSessions.invalidate({ agentId: agent.id }),
    ]);
    handleCloseRename();
  }, [
    agent.id,
    handleCloseRename,
    onSessionTitleChange,
    sessionId,
    updateTitleMutation,
    utils.chat.getAgentSession,
    utils.chat.listAgentSessions,
  ]);

  const renameBusy = updateTitleMutation.isPending;

  const handleTabChange = useCallback(
    (value: string | null): void => {
      if (value === "chat") {
        router.push(`${basePath}/sessions/${sessionId}`);
      } else if (value === "context") {
        router.push(`${basePath}/sessions/${sessionId}?page=context`);
      } else if (value === "subagents") {
        router.push(`${basePath}/sessions/${sessionId}?page=subagents`);
      }
    },
    [router, basePath, sessionId],
  );

  return (
    <>
      <Modal
        opened={editingOpened}
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
              disabled={renameBusy || !session?.title}
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
              <Group gap={4} wrap="nowrap" style={{ minWidth: 0 }}>
                <Text fw={600} size="md" truncate>
                  {sessionTitle}
                </Text>
                <ActionIcon
                  variant="subtle"
                  size="sm"
                  onClick={handleOpenRename}
                  aria-label={t("sessions.rename")}
                  style={{ flexShrink: 0 }}
                >
                  <IconPencil size={rem(14)} />
                </ActionIcon>
              </Group>
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
          <Group gap={4} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
              {sessionTitle}
            </Text>
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={handleOpenRename}
              aria-label={t("sessions.rename")}
              style={{ flexShrink: 0 }}
            >
              <IconPencil size="0.875rem" />
            </ActionIcon>
          </Group>
          <Group gap="xs" wrap="nowrap" style={{ flexShrink: 0 }}>
            {activeTab === "chat" && onOpenRuntime && chatControls}
            {activeTab === "chat" && onOpenRuntime && (
              <ActionIcon
                variant="subtle"
                onClick={onOpenRuntime}
                aria-label="Open agent runtime"
              >
                <IconFolderOpen size="1rem" />
              </ActionIcon>
            )}
          </Group>
        </Group>
        <Tabs
          value={activeTab}
          onChange={handleTabChange}
          variant="default"
          px="sm"
        >
          <Tabs.List>
            <Tabs.Tab
              value="chat"
              leftSection={<IconMessageCircle size={14} />}
            >
              {t("tabs.chat")}
            </Tabs.Tab>
            <Tabs.Tab value="context" leftSection={<IconChartBar size={14} />}>
              {t("tabs.context")}
            </Tabs.Tab>
            <Tabs.Tab
              value="subagents"
              leftSection={<IconGitBranch size={14} />}
            >
              {t("subagents.title")}
            </Tabs.Tab>
          </Tabs.List>
        </Tabs>
      </Box>
    </>
  );
}
