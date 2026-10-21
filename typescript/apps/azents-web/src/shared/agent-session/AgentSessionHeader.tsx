"use client";
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
import {
  IconLayoutSidebarRight,
  IconMenu2,
  IconPencil,
  IconTrash,
} from "@tabler/icons-react";
/**
 * Session title and controls above the persistent conversation workspace.
 */
import { type ReactNode } from "react";
import { AgentAvatar } from "./AgentAvatar";
import { AgentDeletionBadge, AgentDeletionNotice } from "./AgentDeletionStatus";
import { useAgentSessionHeaderController } from "./containers/useAgentSessionHeaderController";
import type { AgentSessionHeaderViewProps } from "./containers/useAgentSessionHeaderController";
import type {
  AgentResponse,
  AgentSessionResponse,
} from "@azents/public-client";

interface AgentSessionHeaderProps {
  agent: AgentResponse;
  session: AgentSessionResponse;
  onUpdateTitle: (title: string | null) => Promise<AgentSessionResponse>;
  onSessionTitleChange?: (session: AgentSessionResponse) => void;
  onTogglePanel: () => void;
  panelOpened: boolean;
  chatControls?: ReactNode;
}

export function AgentSessionHeader(
  props: AgentSessionHeaderProps,
): React.ReactElement {
  return <AgentSessionHeaderView {...useAgentSessionHeaderController(props)} />;
}

export function AgentSessionHeaderView({
  agent,
  onTogglePanel,
  panelOpened,
  chatControls,
  t,
  tPanel,
  mobileNav,
  session,
  renameBusy,
  sessionTitle,
  editingOpened,
  editingTitle,
  setEditingTitle,
  handleOpenRename,
  handleCloseRename,
  handleSubmitRename,
  handleClearTitle,
}: AgentSessionHeaderViewProps): React.ReactElement {
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
            disabled={renameBusy || agent.deletion_status !== null}
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
              disabled={
                renameBusy || !session.title || agent.deletion_status !== null
              }
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
                disabled={
                  !editingTitle.trim() || agent.deletion_status !== null
                }
                onClick={() => void handleSubmitRename()}
              >
                {t("sessions.save")}
              </Button>
            </Group>
          </Group>
        </Stack>
      </Modal>
      <Box
        data-agent-session-header
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
          <Group gap={rem(4)} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            <Text fw={600} size="md" truncate>
              {sessionTitle}
            </Text>
            <AgentDeletionBadge status={agent.deletion_status} />
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={handleOpenRename}
              disabled={agent.deletion_status !== null}
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
          <Group gap={rem(4)} wrap="nowrap" style={{ flex: 1, minWidth: 0 }}>
            <Text fw={600} size="sm" truncate style={{ minWidth: 0 }}>
              {sessionTitle}
            </Text>
            <AgentDeletionBadge status={agent.deletion_status} />
            <ActionIcon
              variant="subtle"
              size="sm"
              onClick={handleOpenRename}
              disabled={agent.deletion_status !== null}
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
        <AgentDeletionNotice status={agent.deletion_status} />
      </Box>
    </>
  );
}
