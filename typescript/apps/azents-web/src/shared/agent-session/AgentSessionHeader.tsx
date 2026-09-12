"use client";

/**
 * Session title and controls above the persistent conversation workspace.
 */

import {
  ActionIcon,
  Box,
  Button,
  Group,
  Modal,
  rem,
  Stack,
  Text,
  TextInput,
} from "@mantine/core";
import { useDocumentTitle } from "@mantine/hooks";
import {
  IconLayoutSidebarRight,
  IconMenu2,
  IconPencil,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { AgentAvatar } from "./AgentAvatar";
import { useAgentFocusedShellMobileNav } from "./AgentFocusedShellMobileNav";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

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

interface AgentSessionHeaderProps {
  agent: AgentResponse;
  session: AgentSessionResponse;
  onUpdateTitle: (title: string | null) => Promise<AgentSessionResponse>;
  onSessionTitleChange?: (session: AgentSessionResponse) => void;
  onTogglePanel: () => void;
  panelOpened: boolean;
  chatControls?: ReactNode;
}

export function AgentSessionHeader({
  agent,
  session: initialSession,
  onUpdateTitle,
  onSessionTitleChange,
  onTogglePanel,
  panelOpened,
  chatControls,
}: AgentSessionHeaderProps): React.ReactElement {
  const t = useTranslations("workspace.agents.detail");
  const tPanel = useTranslations("chat.sessionPanel");
  const mobileNav = useAgentFocusedShellMobileNav();
  const [session, setSession] = useState(initialSession);
  const [renameBusy, setRenameBusy] = useState(false);
  useEffect(() => {
    setSession(initialSession);
  }, [initialSession]);
  const sessionTitle = getSessionDisplayTitle(session, t);
  useDocumentTitle(`${sessionTitle} - Azents`);
  const [editingOpened, setEditingOpened] = useState(false);
  const [editingTitle, setEditingTitle] = useState("");

  const handleOpenRename = useCallback((): void => {
    setEditingTitle(session.title ?? "");
    setEditingOpened(true);
  }, [session.title]);

  const handleCloseRename = useCallback((): void => {
    setEditingOpened(false);
    setEditingTitle("");
  }, []);

  const updateSessionTitle = useCallback(
    async (title: string | null): Promise<void> => {
      setRenameBusy(true);
      try {
        const updatedSession = await onUpdateTitle(title);
        setSession(updatedSession);
        onSessionTitleChange?.(updatedSession);
        handleCloseRename();
      } finally {
        setRenameBusy(false);
      }
    },
    [handleCloseRename, onSessionTitleChange, onUpdateTitle],
  );

  const handleSubmitRename = useCallback(async (): Promise<void> => {
    const title = editingTitle.trim();
    if (!title) {
      return;
    }
    await updateSessionTitle(title);
  }, [editingTitle, updateSessionTitle]);

  const handleClearTitle = useCallback(async (): Promise<void> => {
    await updateSessionTitle(null);
  }, [updateSessionTitle]);

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
              disabled={renameBusy || !session.title}
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
          gap={0}
          px="lg"
          pt="sm"
          pb="xs"
          wrap="nowrap"
        >
          <Group gap={4} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
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
          {chatControls ? (
            <Box style={{ flexShrink: 0 }}>{chatControls}</Box>
          ) : null}
          <ActionIcon
            ml="xs"
            variant={panelOpened ? "light" : "subtle"}
            onClick={onTogglePanel}
            aria-label={tPanel("toggle")}
            aria-expanded={panelOpened}
          >
            <IconLayoutSidebarRight size={rem(18)} />
          </ActionIcon>
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
            {chatControls}
            <ActionIcon
              variant={panelOpened ? "light" : "subtle"}
              onClick={onTogglePanel}
              aria-label={tPanel("toggle")}
              aria-expanded={panelOpened}
            >
              <IconLayoutSidebarRight size={rem(18)} />
            </ActionIcon>
          </Group>
        </Group>
      </Box>
    </>
  );
}
