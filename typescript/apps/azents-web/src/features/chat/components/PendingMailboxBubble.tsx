"use client";

import {
  ActionIcon,
  Badge,
  Box,
  Group,
  Loader,
  Paper,
  Stack,
  Text,
  Tooltip,
} from "@mantine/core";
import {
  IconBrandSlack,
  IconTargetArrow,
  IconTrash,
} from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MessageActionRow } from "./MessageActionRow";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
import type { PendingMailboxEntry } from "../hooks/pendingMailboxState";

interface PendingMailboxBubbleProps {
  entry: PendingMailboxEntry;
  onDelete: (correlation: string) => void;
}

type PendingAction = Extract<
  PendingMailboxEntry["item"]["presentation"],
  { type: "action_message" }
>["action"];

function skillNameFromPath(skillPath: string): string {
  const parts = skillPath.split("/").filter(Boolean);
  const last = parts.at(-1) ?? skillPath;
  return last === "SKILL.md"
    ? (parts.at(-2) ?? last)
    : last.replace(/\.md$/u, "");
}

function actionDetailLabel(action: PendingAction): string {
  switch (action.type) {
    case "command":
      return `/${action.name}`;
    case "goal":
      return "/goal";
    case "skill":
      return `/${skillNameFromPath(action.skill_path)}`;
    case "create_git_worktree":
      return `/worktree ${action.starting_ref}`;
    case "cleanup_orphan_git_worktrees":
      return "/cleanup-worktrees";
  }
}

export function PendingMailboxBubble({
  entry,
  onDelete,
}: PendingMailboxBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");
  const { item, deleting } = entry;
  const presentation = item.presentation;
  const text =
    presentation.type === "external_channel_message"
      ? presentation.body
      : presentation.type === "action_message"
        ? presentation.message
        : presentation.content;
  const commonActions = (
    <MessageActionRow
      content={text}
      createdAt={item.created_at}
      align="user"
      inferenceProfile={
        "requested_inference_profile" in presentation
          ? presentation.requested_inference_profile
          : null
      }
      additionalActions={
        <Tooltip label={t("delete")} withArrow position="left">
          <ActionIcon
            size="sm"
            variant="subtle"
            color="gray"
            aria-label={t("delete")}
            disabled={deleting}
            onClick={() => onDelete(`${item.mailbox_item_id}:${item.item_key}`)}
          >
            {deleting ? <Loader size="xs" /> : <IconTrash size={14} />}
          </ActionIcon>
        </Tooltip>
      }
    />
  );

  if (presentation.type === "agent_message") {
    return (
      <MessageMetadataSurface>
        <Paper
          p="sm"
          mb="md"
          radius="lg"
          withBorder
          style={{ opacity: deleting ? 0.45 : 0.6 }}
        >
          <Stack gap={4}>
            <Text size="xs" fw={700} c="dimmed">
              Agent · {presentation.message_kind}
            </Text>
            <Text style={{ whiteSpace: "pre-wrap" }}>
              {presentation.content}
            </Text>
            {commonActions}
          </Stack>
        </Paper>
      </MessageMetadataSurface>
    );
  }

  if (presentation.type === "goal_continuation") {
    return (
      <MessageMetadataSurface>
        <Group
          gap="xs"
          mb="md"
          wrap="nowrap"
          style={{ opacity: deleting ? 0.45 : 0.6 }}
        >
          <IconTargetArrow size={15} aria-hidden="true" />
          <Box style={{ minWidth: 0 }}>
            <Text size="xs" fw={700} c="dimmed">
              Goal continuation
            </Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {presentation.content}
            </Text>
            {commonActions}
          </Box>
        </Group>
      </MessageMetadataSurface>
    );
  }

  if (presentation.type === "external_channel_message") {
    return (
      <MessageMetadataSurface>
        <Paper
          withBorder
          radius="md"
          p="sm"
          mb="md"
          style={{ opacity: deleting ? 0.45 : 0.6 }}
        >
          <Stack gap="xs">
            <Group gap="xs" wrap="nowrap">
              <IconBrandSlack size={15} aria-hidden="true" />
              <Text size="xs" fw={700} truncate>
                {presentation.sender_display_name ?? "External sender"}
              </Text>
              <Text size="xs" c="dimmed" truncate>
                {presentation.resource_label}
              </Text>
              <Badge size="xs" variant="light">
                {presentation.lifecycle}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed">
              {presentation.provider} · {presentation.resource_type} ·{" "}
              {presentation.authorization} · {presentation.revision_kind}
            </Text>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {presentation.body ?? "[No external message body]"}
            </Text>
            {presentation.original_url && (
              <Text size="xs" c="blue">
                Reference: {presentation.original_url}
              </Text>
            )}
            {commonActions}
          </Stack>
        </Paper>
      </MessageMetadataSurface>
    );
  }

  if (presentation.type === "action_message") {
    return (
      <MessageMetadataSurface>
        <Paper
          withBorder
          radius="md"
          p="sm"
          mb="md"
          style={{ opacity: deleting ? 0.45 : 0.6 }}
        >
          <Stack gap="xs">
            <Group gap="xs">
              <Badge color="blue" variant="light">
                Pending action
              </Badge>
              <Text size="xs" fw={700}>
                {actionDetailLabel(presentation.action)}
              </Text>
            </Group>
            <Text size="sm" style={{ whiteSpace: "pre-wrap" }}>
              {presentation.message}
            </Text>
            {commonActions}
          </Stack>
        </Paper>
      </MessageMetadataSurface>
    );
  }

  const attachments = presentation.attachments ?? [];
  const action = null;
  return (
    <MessageMetadataSurface>
      <InputBufferBubbleFrame
        content={text ?? ""}
        action={action}
        attachments={attachments}
        opacity={deleting ? 0.45 : 0.6}
        actions={commonActions}
      />
    </MessageMetadataSurface>
  );
}
