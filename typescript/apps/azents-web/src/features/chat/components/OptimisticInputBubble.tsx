"use client";

/** before server ack user input displaying optimistic bubble. */

import { Group } from "@mantine/core";
import { useTranslations } from "next-intl";
import { ChatCopyButton } from "./ChatCopyButton";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import type { PendingInputBuffer } from "../types";

interface OptimisticInputBubbleProps {
  buffer: PendingInputBuffer;
}

export function OptimisticInputBubble({
  buffer,
}: OptimisticInputBubbleProps): React.ReactElement {
  const t = useTranslations("chat.pendingInput");

  return (
    <InputBufferBubbleFrame
      content={buffer.content}
      attachments={buffer.attachments}
      attachmentFiles={buffer.attachmentFiles}
      opacity={0.6}
      actions={
        <Group gap={2} mt={4} justify="flex-end">
          <ChatCopyButton
            value={buffer.content}
            copyLabel={t("copy")}
            copiedLabel={t("copied")}
            position="left"
          />
        </Group>
      }
    />
  );
}
