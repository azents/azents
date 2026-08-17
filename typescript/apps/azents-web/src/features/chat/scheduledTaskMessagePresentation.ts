import type { ChatMessage } from "./types";

export interface ScheduledTaskMessagePresentation {
  title: string | null;
  schedule: string | null;
  scheduleCanonical: string | null;
  scheduledFor: string | null;
  scheduledForCanonical: string | null;
  prompt: string | null;
  fallbackContent: string;
}

function lineValue(content: string, label: string): string | null {
  const prefix = `${label}: `;
  const line = content
    .split("\n")
    .find((candidate) => candidate.startsWith(prefix));
  return line?.slice(prefix.length).trim() || null;
}

export function scheduledTaskMessagePresentation(
  message: ChatMessage,
): ScheduledTaskMessagePresentation {
  const content = message.content ?? "";
  const promptMarker = "\nPrompt:\n";
  const promptIndex = content.indexOf(promptMarker);
  const metadataTitle = message.metadata?.title?.trim() || null;

  return {
    title: metadataTitle ?? lineValue(content, "Title"),
    schedule: lineValue(content, "Schedule"),
    scheduleCanonical: lineValue(content, "Schedule details"),
    scheduledFor: lineValue(content, "Scheduled for"),
    scheduledForCanonical: lineValue(content, "Scheduled for details"),
    prompt:
      promptIndex < 0 ? null : content.slice(promptIndex + promptMarker.length),
    fallbackContent: content,
  };
}
