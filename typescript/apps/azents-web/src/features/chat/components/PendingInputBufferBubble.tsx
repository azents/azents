"use client";

/** model turn not yet not injected user input bubble. */

import { ActionIcon, Group, Loader, Tooltip } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { ChatCopyButton } from "./ChatCopyButton";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import type { PendingInputBuffer } from "../types";

interface PendingInputBufferBubbleProps {
  buffer: PendingInputBuffer;
  onDelete: (bufferId: string) => void;
}

export function PendingInputBufferBubble({
  buffer,
  onDelete,
}: PendingInputBufferBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");
  const deleting = buffer.status === "deleting";

  return (
    <InputBufferBubbleFrame
      content={buffer.content}
      attachments={buffer.attachments}
      attachmentFiles={buffer.attachmentFiles}
      opacity={deleting ? 0.45 : 0.6}
      actions={
        <Group gap={2} mt={4} justify="flex-end">
          <ChatCopyButton
            value={buffer.content}
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            position="left"
          />
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
        </Group>
      }
    />
  );
}
