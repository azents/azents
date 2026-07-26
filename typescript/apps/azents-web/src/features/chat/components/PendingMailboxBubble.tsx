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
import { AgentMessageDisclosure } from "./AgentMessageDisclosure";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MessageActionRow } from "./MessageActionRow";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
import type { PendingMailboxEntry } from "../hooks/pendingMailboxState";

interface PendingMailboxBubbleProps {
  entry: PendingMailboxEntry;
  onDelete: (correlation: string) => void;
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
        <AgentMessageDisclosure
          title={`Agent · ${presentation.message_kind}`}
          content={presentation.content}
          actions={commonActions}
          opacity={deleting ? 0.45 : 0.6}
        />
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
        <InputBufferBubbleFrame
          content={presentation.message}
          action={presentation.action}
          attachments={[]}
          opacity={deleting ? 0.45 : 0.6}
          actions={commonActions}
        />
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
