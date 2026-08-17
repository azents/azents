import assert from "node:assert/strict";
import test from "node:test";
import { scheduledTaskMessagePresentation } from "./scheduledTaskMessagePresentation.ts";
import type { ChatMessage } from "./types.ts";

function message(
  content: string,
  metadata: Record<string, string> | null = null,
): ChatMessage {
  return {
    id: "scheduled-1",
    role: "user",
    content,
    createdAt: "2026-08-17T13:00:00Z",
    status: "complete",
    metadata,
  };
}

void test("extracts structured Scheduled Task display fields and exact prompt", () => {
  const prompt = "Prepare the report.\nKeep this line exactly.";
  const result = scheduledTaskMessagePresentation(
    message(
      [
        "Scheduled Task work is due.",
        "Title: Content title",
        "Schedule: Every weekday at 9:00 AM EDT",
        "Schedule details: 0 9 * * 1-5 (America/New_York)",
        "Scheduled for: August 17, 2026 at 9:00 AM EDT",
        "Scheduled for details: 2026-08-17T13:00:00Z",
        "Execution guidance: Continue autonomously.",
        "Prompt:",
        prompt,
      ].join("\n"),
      { source: "scheduled_task", title: "Metadata title" },
    ),
  );

  assert.deepEqual(result, {
    title: "Metadata title",
    schedule: "Every weekday at 9:00 AM EDT",
    scheduleCanonical: "0 9 * * 1-5 (America/New_York)",
    scheduledFor: "August 17, 2026 at 9:00 AM EDT",
    scheduledForCanonical: "2026-08-17T13:00:00Z",
    prompt,
    fallbackContent: result.fallbackContent,
  });
});

void test("keeps legacy Scheduled Task content as a complete fallback", () => {
  const content = "Scheduled Task work is due.";
  const result = scheduledTaskMessagePresentation(message(content));

  assert.equal(result.title, null);
  assert.equal(result.prompt, null);
  assert.equal(result.fallbackContent, content);
});
