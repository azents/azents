import type { ChatMessage, WorktreeOperation } from "./types";

export interface WorktreeOperationHistoryEvent {
  createdAt: string;
  operation: WorktreeOperation;
}

function mergeWorktreeOperation(
  current: WorktreeOperation,
  incoming: WorktreeOperation,
): WorktreeOperation {
  const eventsById = new Map<string, WorktreeOperation["events"][number]>();
  for (const event of current.events) {
    eventsById.set(event.id, event);
  }
  for (const event of incoming.events) {
    eventsById.set(event.id, event);
  }
  return {
    execution:
      incoming.execution.updated_at >= current.execution.updated_at
        ? incoming.execution
        : current.execution,
    events: [...eventsById.values()].sort(
      (left, right) => left.sequence - right.sequence,
    ),
  };
}

export function applyWorktreeOperationHistoryEvent(
  messages: ChatMessage[],
  event: WorktreeOperationHistoryEvent,
): ChatMessage[] {
  const index = messages.findIndex(
    (message) =>
      message.worktreeOperation?.execution.id === event.operation.execution.id,
  );
  if (index === -1) {
    return [
      ...messages,
      {
        id: `worktree-operation:${event.operation.execution.id}`,
        role: "worktree_operation",
        content: null,
        createdAt: event.createdAt,
        status: "complete",
        worktreeOperation: event.operation,
      },
    ];
  }
  return messages.map((message, messageIndex) =>
    messageIndex === index && message.worktreeOperation
      ? {
          ...message,
          worktreeOperation: mergeWorktreeOperation(
            message.worktreeOperation,
            event.operation,
          ),
        }
      : message,
  );
}
