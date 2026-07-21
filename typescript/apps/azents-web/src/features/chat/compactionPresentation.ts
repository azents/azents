import type { ChatMessage } from "./types";

function compactionId(message: ChatMessage): string | null {
  const value = message.metadata?.compaction_id;
  return value && value.length > 0 ? value : null;
}

export function completedCompactionIds(
  messages: readonly ChatMessage[],
): ReadonlySet<string> {
  const completedIds = new Set<string>();
  for (const message of messages) {
    if (message.role !== "compaction") {
      continue;
    }
    const id = compactionId(message);
    if (id !== null) {
      completedIds.add(id);
    }
  }
  return completedIds;
}

export function isCompactionInProgressMarker(
  message: ChatMessage,
  completedIds: ReadonlySet<string>,
): boolean {
  if (message.role !== "compaction_started") {
    return false;
  }
  const id = compactionId(message);
  return id === null || !completedIds.has(id);
}
