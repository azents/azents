"use client";

/** before server ack user input displaying optimistic bubble. */

import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import { MessageActionRow } from "./MessageActionRow";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
import type { PendingInputBuffer } from "../types";

interface OptimisticInputBubbleProps {
  buffer: PendingInputBuffer;
}

export function OptimisticInputBubble({
  buffer,
}: OptimisticInputBubbleProps): React.ReactElement {
  return (
    <MessageMetadataSurface>
      <InputBufferBubbleFrame
        content={buffer.content}
        action={buffer.action}
        attachments={buffer.attachments}
        attachmentFiles={buffer.attachmentFiles}
        opacity={0.6}
        actions={
          <MessageActionRow
            content={buffer.content}
            createdAt={buffer.createdAt}
            align="user"
            inferenceProfile={buffer.requestedInferenceProfile}
          />
        }
      />
    </MessageMetadataSurface>
  );
}
