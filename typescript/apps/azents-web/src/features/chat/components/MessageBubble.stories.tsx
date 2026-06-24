import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  attachmentToolCall,
  createChatMessage,
  imageAttachment,
  markdownSample,
  preparingToolCall,
  textAttachment,
} from "../story-fixtures";
import { MessageBubble } from "./MessageBubble";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: MessageBubble,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(860)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof MessageBubble>;

export default meta;

type Story = StoryObj<typeof meta>;

export const UserText = {
  args: {
    message: createChatMessage({
      id: "user-text",
      role: "user",
      content: "Can you summarize the build output?",
    }),
  },
} satisfies Story;

export const EditableUserText = {
  args: {
    message: createChatMessage({
      id: "user-editable",
      role: "user",
      content: "Summarize this run and call out failures.",
    }),
    editable: true,
    onEdit: () => {},
  },
} satisfies Story;

export const DimmedAfterEdit = {
  args: {
    message: createChatMessage({
      id: "assistant-dimmed",
      content: "This response is below the message currently being edited.",
    }),
    dimmed: true,
  },
} satisfies Story;

export const AssistantMarkdown = {
  args: {
    message: createChatMessage({
      id: "assistant-markdown",
      content: markdownSample,
    }),
  },
} satisfies Story;

export const ErrorResponse = {
  args: {
    message: createChatMessage({
      id: "error-response",
      role: "error",
      content: "Compaction failed: summary model returned no text.",
    }),
  },
} satisfies Story;

export const Streaming = {
  args: {
    message: createChatMessage({
      id: "assistant-streaming",
      content: "I am checking the Storybook build",
      status: "partial",
    }),
  },
} satisfies Story;

export const ThinkingOnly = {
  args: {
    message: createChatMessage({
      id: "assistant-thinking",
      content: null,
      status: "partial",
      reasoningSummary:
        "Need to verify provider coverage, then check whether each component can render from static props.",
    }),
  },
} satisfies Story;

export const WithToolCall = {
  args: {
    message: createChatMessage({
      id: "assistant-tool-call",
      content: null,
      toolCalls: [attachmentToolCall],
    }),
  },
} satisfies Story;

export const WithPreparingToolCall = {
  args: {
    message: createChatMessage({
      id: "assistant-tool-call-preparing",
      content: null,
      status: "partial",
      toolCalls: [preparingToolCall],
    }),
  },
} satisfies Story;

export const WithAttachments = {
  args: {
    message: createChatMessage({
      id: "assistant-attachments",
      content: "I attached the screenshot and run log.",
      attachments: [imageAttachment, textAttachment],
    }),
  },
} satisfies Story;

export const GoalContinuationIndicator = {
  args: {
    message: createChatMessage({
      id: "goal-continuation",
      role: "goal_continuation",
      content: null,
    }),
  },
} satisfies Story;

export const GoalUpdatedIndicator = {
  args: {
    message: createChatMessage({
      id: "goal-updated",
      role: "goal_updated",
      content: null,
    }),
  },
} satisfies Story;

export const InterruptedIndicator = {
  args: {
    message: createChatMessage({
      id: "interrupted",
      role: "interrupted",
      content: null,
    }),
  },
} satisfies Story;

export const GoalBriefing = {
  args: {
    message: createChatMessage({
      id: "goal-briefing",
      role: "goal_briefing",
      content: "Ship durable Goal briefing cards",
      metadata: {
        objective: "Ship durable Goal briefing cards",
        completed_at: "2026-06-15T12:45:00.000Z",
        duration_seconds: "930",
      },
    }),
  },
} satisfies Story;
