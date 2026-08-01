"use client";

import { ActionIcon, Loader, Tooltip } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { pendingInputBufferMessage } from "../pendingMessageProjection";
import { MessageBubble } from "./MessageBubble";
import type { CurrentWorkspaceProfile } from "../senderPresentation";
import type { PendingInputBuffer } from "../types";

interface PendingInputBufferBubbleProps {
  buffer: PendingInputBuffer;
  currentWorkspaceProfile?: CurrentWorkspaceProfile | null;
  onDelete: (bufferId: string) => void;
}

export function PendingInputBufferBubble({
  buffer,
  currentWorkspaceProfile = null,
  onDelete,
}: PendingInputBufferBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");
  const deleting = buffer.status === "deleting";
  const message = pendingInputBufferMessage(
    buffer,
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
            onClick={() => onDelete(buffer.id)}
          >
            {deleting ? <Loader size="xs" /> : <IconTrash size={14} />}
          </ActionIcon>
        </Tooltip>
      }
    />
  );
}
