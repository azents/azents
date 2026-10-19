import { createChatMessage } from "./story-fixtures";
import type { ChatMessage } from "@azents/session-core/types";

/** Composed production message routes used by layout and full ChatView stories. */
export const standardDisclosureMessages: ChatMessage[] = [
  createChatMessage({
    id: "standard-judgment",
    role: "routine_judgment",
    content: null,
    routineJudgment: {
      provider: "openai",
      model: "saved-model",
      observation: {
        type: "AVAILABLE",
        judgmentId: "standard-judgment",
        status: "completed",
        error: null,
        items: [
          {
            routineId: "traffic",
            slug: "traffic",
            title: "Traffic anomalies",
            act: true,
          },
        ],
        callUsage: null,
      },
    },
  }),
  createChatMessage({
    id: "standard-work",
    role: "routine_trigger",
    routineInput: {
      content: "Check traffic and record a silent result.",
      executions: [],
    },
  }),
  createChatMessage({
    id: "standard-continuation",
    role: "routine_continuation",
    routineInput: {
      content: "Continue the original traffic investigation.",
      executions: [],
    },
  }),
  createChatMessage({
    id: "standard-schedule",
    role: "user",
    content:
      "Scheduled Task work is due.\nTitle: Daily report\nSchedule: Every day\nPrompt:\nPrepare a verified report.",
    metadata: { source: "scheduled_task", title: "Daily report" },
  }),
  createChatMessage({
    id: "standard-agent",
    role: "user",
    content: "The independent review is complete.",
    metadata: { source: "agent_mailbox", source_path: "/root/reviewer" },
  }),
  createChatMessage({
    id: "standard-channel",
    role: "user",
    content: "Check the release status and report blockers.",
    metadata: {
      source: "external_channel",
      provider: "discord",
      prompt_role: "invocation",
      sender_display_name: "Release team",
      resource_label: "#release",
      original_url: "https://example.com/message",
    },
  }),
  createChatMessage({
    id: "standard-goal",
    role: "goal_continuation",
    content: "Continue the current goal.",
  }),
  createChatMessage({
    id: "standard-channel-continuation",
    role: "external_channel_continuation",
    content: "Continue channel work.",
  }),
  createChatMessage({
    id: "standard-goal-updated",
    role: "goal_updated",
    content: "Goal updated.",
  }),
];

export const standardTranscriptMessages: ChatMessage[] = [
  ...standardDisclosureMessages,
  createChatMessage({
    id: "standard-human",
    role: "user",
    content: "Please keep the release checks running.",
  }),
  createChatMessage({
    id: "standard-reasoning",
    content: null,
    reasoningSummary: "Inspect the official sources and preserve the results.",
  }),
  createChatMessage({
    id: "standard-assistant",
    content:
      "Both checks are complete.\n\n- **Traffic:** no meaningful change.\n- **Release news:** no official announcement.\n\nI will keep watching for meaningful updates.",
  }),
  createChatMessage({
    id: "standard-error",
    role: "error",
    content: "The source could not be reached.",
  }),
  createChatMessage({
    id: "standard-interrupted",
    role: "interrupted",
    content: null,
  }),
];
