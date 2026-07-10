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

export const AgentMailboxMessage = {
  args: {
    message: createChatMessage({
      id: "agent-mailbox",
      role: "user",
      content:
        "Checked the deployment logs. The rollout failed because the readiness probe timed out.",
      metadata: {
        source: "agent_mailbox",
        message_kind: "send_message",
        source_path: "/root/deploy-check",
        target_path: "/root",
      },
    }),
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

export const FailedRunErrorResponse = {
  args: {
    message: createChatMessage({
      id: "failed-run-error-response",
      role: "error",
      content: "An internal error occurred.",
      metadata: {
        failed_run_kind: "failed_run",
        failed_run_finalization_reason: "retry_exhausted",
        failed_run_failed_attempt_count: "10",
        failed_run_max_retries: "10",
        failed_run_last_error_type: "RuntimeError",
        failed_run_retryability: "unknown",
        failed_run_failure_code: "",
        failed_run_action_hint: "Check provider status or try again later.",
      },
      failedRunFailure: {
        kind: "failed_run",
        finalization_reason: "retry_exhausted",
        failed_attempt_count: 10,
        max_retries: 10,
        last_error_type: "RuntimeError",
        retryability: "unknown",
        failure_code: null,
        action_hint: "Check provider status or try again later.",
        attempts: [
          {
            attemptNumber: 10,
            userMessage: "Runtime operation failed after provider timeout.",
            errorType: "RuntimeError",
            source: "runtime",
            failedAt: "2026-05-01T10:00:00.000Z",
            backoffSeconds: 30,
            nextRetryAt: "2026-05-01T10:00:30.000Z",
            retryability: "unknown",
            failureCode: null,
            truncated: false,
          },
        ],
      },
    }),
    failedRunRetryAction: {
      canRetry: true,
      isPending: false,
      onRetry: () => {},
    },
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
        "<!-- internal marker -->\n\n## Verifying provider coverage with a deliberately long preview that truncates consistently across mobile and desktop\n\nNeed to check whether each component can render from static props.\n\n<!— -->",
    }),
  },
} satisfies Story;

export const ThinkingWithoutSummary = {
  args: {
    message: createChatMessage({
      id: "assistant-thinking-without-summary",
      content: null,
      status: "partial",
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

export const SkillLoadedIndicator = {
  args: {
    message: createChatMessage({
      id: "skill-loaded",
      role: "skill_loaded",
      content:
        "---\nname: ship-pr\n---\n\n# Ship PR\n\nCreate and monitor a pull request.",
      metadata: {
        name: "ship-pr",
      },
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
