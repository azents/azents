import type {
  ChatPresentationItem,
  ToolActivityPresentationItem,
} from "@azents/session-core/toolActivityPresentation";
import type { ChatMessage } from "@azents/session-core/types";

export interface ActivityRunBinding {
  runId: string;
  activityId: string;
}

export function latestRunActivitySource(
  items: ChatPresentationItem[],
  messages: ChatMessage[],
): ToolActivityPresentationItem | null {
  let boundaryIndex = -1;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const role = messages[index]?.role;
    if (role === "user" || role === "run_complete") {
      boundaryIndex = index;
      break;
    }
  }
  for (let index = items.length - 1; index >= 0; index -= 1) {
    const item = items[index];
    if (
      item?.type === "activity" &&
      item.activity.startMessageIndex > boundaryIndex
    ) {
      return item;
    }
  }
  return null;
}

export function boundRunActivitySource(
  items: ChatPresentationItem[],
  binding: ActivityRunBinding | null,
  runId: string | null,
): ToolActivityPresentationItem | null {
  if (binding === null || binding.runId !== runId) {
    return null;
  }
  return (
    items.find(
      (item): item is ToolActivityPresentationItem =>
        item.type === "activity" && item.id === binding.activityId,
    ) ?? null
  );
}
