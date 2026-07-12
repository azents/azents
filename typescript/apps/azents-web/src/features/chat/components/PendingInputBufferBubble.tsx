"use client";

/** model turn not yet not injected user input bubble. */

import { ActionIcon, Loader, Tooltip } from "@mantine/core";
import { IconTrash } from "@tabler/icons-react";
import { useTranslations } from "next-intl";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MessageActionRow } from "./MessageActionRow";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
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
    <MessageMetadataSurface>
      <InputBufferBubbleFrame
        content={buffer.content}
        action={buffer.action}
        attachments={buffer.attachments}
        attachmentFiles={buffer.attachmentFiles}
        opacity={deleting ? 0.45 : 0.6}
        actions={
          <MessageActionRow
            content={buffer.content}
            createdAt={buffer.createdAt}
            align="user"
            inferenceProfile={buffer.requestedInferenceProfile}
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
        }
      />
    </MessageMetadataSurface>
  );
}
