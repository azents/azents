"use client";

import { ActionIcon, Loader, Tooltip } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { pendingMailboxMessage } from "../pendingMessageProjection";
import { MessageBubble } from "./MessageBubble";
import type { PendingMailboxEntry } from "../hooks/pendingMailboxState";
import type { CurrentWorkspaceProfile } from "../senderPresentation";

interface PendingMailboxBubbleProps {
  entry: PendingMailboxEntry;
  currentWorkspaceProfile?: CurrentWorkspaceProfile | null;
  onDelete: (correlation: string) => void;
}

export function PendingMailboxBubble({
  entry,
  currentWorkspaceProfile = null,
  onDelete,
}: PendingMailboxBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");
  const { item, deleting } = entry;
  const message = pendingMailboxMessage(
    entry,
    currentWorkspaceProfile?.userId ?? null,
  );

  return (
    <MessageBubble
      message={message}
      currentWorkspaceProfile={currentWorkspaceProfile}
      opacity={deleting ? 0.45 : 0.6}
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
}
