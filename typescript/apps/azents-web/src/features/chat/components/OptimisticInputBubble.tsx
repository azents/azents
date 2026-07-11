"use client";

/** before server ack user input displaying optimistic bubble. */

import { Group } from "@mantine/core";
import { useTranslations } from "next-intl";
import { ChatCopyButton } from "./ChatCopyButton";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import {
  MessageMetadataFooter,
  MessageMetadataSurface,
} from "./MessageMetadataFooter";
import type { PendingInputBuffer } from "../types";

interface OptimisticInputBubbleProps {
  buffer: PendingInputBuffer;
}

export function OptimisticInputBubble({
  buffer,
}: OptimisticInputBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");

  return (
    <MessageMetadataSurface>
      <InputBufferBubbleFrame
        content={buffer.content}
        action={buffer.action}
        attachments={buffer.attachments}
        attachmentFiles={buffer.attachmentFiles}
        opacity={0.6}
        actions={
          <Group gap="xs" mt="2xs" justify="space-between" wrap="nowrap">
            <MessageMetadataFooter
              createdAt={buffer.createdAt}
              profile={buffer.requestedInferenceProfile}
            />
            <ChatCopyButton
              value={buffer.content}
              copyLabel={t("copy")}
              copiedLabel={t("copied")}
              position="left"
            />
          </Group>
        }
      />
    </MessageMetadataSurface>
  );
}
