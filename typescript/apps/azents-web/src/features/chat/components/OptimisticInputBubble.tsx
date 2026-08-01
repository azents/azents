"use client";

import { pendingInputBufferMessage } from "../pendingMessageProjection";
import { MessageBubble } from "./MessageBubble";
import type { CurrentWorkspaceProfile } from "../senderPresentation";
import type { PendingInputBuffer } from "../types";

interface OptimisticInputBubbleProps {
  buffer: PendingInputBuffer;
  currentWorkspaceProfile?: CurrentWorkspaceProfile | null;
}

export function OptimisticInputBubble({
  buffer,
  currentWorkspaceProfile = null,
}: OptimisticInputBubbleProps): React.ReactElement {
  return (
    <MessageBubble
      message={pendingInputBufferMessage(
        buffer,
        currentWorkspaceProfile?.userId ?? null,
      )}
      currentWorkspaceProfile={currentWorkspaceProfile}
      opacity={0.6}
    />
  );
}
