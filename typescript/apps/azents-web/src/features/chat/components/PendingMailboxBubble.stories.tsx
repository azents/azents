import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { PendingMailboxBubble } from "./PendingMailboxBubble";
import type { PendingMailboxEntry } from "../hooks/pendingMailboxState";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const base = {
  mailbox_item_id: "mailbox-story",
  session_id: "session-story",
  kind: "mixed",
  scheduling_mode: "fifo",
  created_at: "2026-07-26T10:00:00.000Z",
};

const item = (
  itemKey: string,
  presentation: PendingMailboxEntry["item"]["presentation"],
): PendingMailboxEntry => ({
  envelope: { ...base, items: [] },
  item: {
    id: `${base.mailbox_item_id}:${itemKey}`,
    mailbox_item_id: base.mailbox_item_id,
    item_key: itemKey,
    kind: presentation.type,
    state: "pending",
    created_at: base.created_at,
    presentation,
  },
  deleting: false,
});

const meta = {
  title: "chat/PendingMailboxBubble",
  component: PendingMailboxBubble,
  args: {
    entry: item("user", {
      type: "user_message",
      content: "Review the latest changes and summarize the risks.",
      attachments: [],
      requested_inference_profile: {
        model_target_label: "quality",
        reasoning_effort: "high",
      },
    }),
    onDelete: () => {},
  },
} satisfies Meta<typeof PendingMailboxBubble>;

export default meta;
type Story = StoryObj<typeof meta>;

export const UserMessage: Story = {};

export const AgentMessage: Story = {
  args: {
    entry: item("agent", {
      type: "agent_message",
      message_kind: "send_message",
      content: "A collaborating agent supplied additional context.",
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", {
      name: "Agent · send_message",
    });
    await expect(
      canvas.queryByText("A collaborating agent supplied additional context."),
    ).toBeNull();
    await userEvent.click(trigger);
    await expect(
      canvas.getByText("A collaborating agent supplied additional context."),
    ).toBeVisible();
  },
};

export const GoalContinuation: Story = {
  args: {
    entry: item("goal", {
      type: "goal_continuation",
      content: "Continue the current goal using the latest checkpoint.",
      requested_inference_profile: null,
    }),
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("Goal continuation"),
    ).toBeVisible();
  },
};

export const ExternalChannel: Story = {
  args: {
    entry: item("external", {
      type: "external_channel_message",
      provider: "slack",
      resource_label: "engineering",
      resource_type: "channel",
      external_message_id: "message-1",
      sender_display_name: "Taylor",
      author_type: "human",
      authorization: "context_only",
      body: "A safe pending external-channel projection.",
      original_url: null,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("A safe pending external-channel projection."),
    ).toBeVisible();
    await expect(canvas.getByText(/slack · channel/)).toBeVisible();
  },
};

export const DiscordExternalChannel: Story = {
  args: {
    entry: item("discord-external", {
      type: "external_channel_message",
      provider: "discord",
      resource_label: "deployment",
      resource_type: "thread",
      external_message_id: "message-2",
      sender_display_name: "Alice",
      author_type: "human",
      authorization: "authorized_invocation",
      body: "Continue the bound Discord thread without another mention.",
      original_url: null,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/discord · thread/)).toBeVisible();
  },
};

export const MobileExternalChannelOverflow: Story = {
  args: {
    entry: item("mobile-discord-external", {
      type: "external_channel_message",
      provider: "discord",
      resource_label:
        "a-very-long-discord-thread-name-without-natural-break-points",
      resource_type: "thread",
      external_message_id: "message-mobile",
      sender_display_name: "A participant with a long display name",
      author_type: "human",
      authorization: "authorized_invocation",
      body: "Please investigate this unbroken-reference-without-natural-break-points-and-keep-the-card-inside-the-mobile-viewport.",
      original_url:
        "https://discord.com/channels/1440378991704932494/1442342792822263808/1531600000000000000",
    }),
  },
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  play: async ({ canvasElement }) => {
    await expect(canvasElement.scrollWidth).toBeLessThanOrEqual(
      canvasElement.clientWidth,
    );
  },
};

export const TurnAction: Story = {
  args: {
    entry: item("action", {
      type: "action_message",
      action: { type: "command", name: "review" },
      message: "Run the review command after the current turn.",
      requested_inference_profile: null,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Pending action")).toBeVisible();
    await expect(canvas.getByText("/review")).toBeVisible();
  },
};

export const CleanupWorktreesAction: Story = {
  args: {
    entry: item("cleanup", {
      type: "action_message",
      action: { type: "cleanup_orphan_git_worktrees" },
      message: "Clean up orphaned worktrees before continuing.",
      requested_inference_profile: null,
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Pending action")).toBeVisible();
    await expect(canvas.getByText("/cleanup-worktrees")).toBeVisible();
  },
};

export const CompoundEnvelopeOrder: Story = {
  render: (args) => (
    <>
      <PendingMailboxBubble
        {...args}
        entry={item("first", {
          type: "external_channel_message",
          provider: "slack",
          resource_label: "engineering",
          resource_type: "channel",
          external_message_id: "message-1",
          sender_display_name: "Taylor",
          author_type: "human",
          authorization: "context_only",
          body: "First item remains first.",
          original_url: null,
        })}
      />
      <PendingMailboxBubble
        {...args}
        entry={item("second", {
          type: "external_channel_message",
          provider: "slack",
          resource_label: "engineering",
          resource_type: "channel",
          external_message_id: "message-2",
          sender_display_name: "Morgan",
          author_type: "human",
          authorization: "context_only",
          body: "Second item remains contiguous.",
          original_url: null,
        })}
      />
    </>
  ),
};

export const Deleting: Story = {
  args: {
    entry: {
      ...item("delete", {
        type: "goal_continuation",
        content: "This pending item is being removed.",
        requested_inference_profile: null,
      }),
      deleting: true,
    },
  },
};
