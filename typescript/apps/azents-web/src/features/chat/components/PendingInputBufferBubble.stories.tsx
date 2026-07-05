import { OptimisticInputBubble } from "./OptimisticInputBubble";
import { PendingInputBufferBubble } from "./PendingInputBufferBubble";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "chat/PendingInputBufferBubble",
  component: PendingInputBufferBubble,
  args: {
    buffer: {
      id: "buffer-1",
      sessionId: "session-1",
      content: "Please continue with this additional context.",
      attachments: [],
      metadata: { source: "web" },
      createdAt: "2026-05-19T00:00:00Z",
      status: "pending",
    },
    onDelete: () => {},
  },
} satisfies Meta<typeof PendingInputBufferBubble>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Pending: Story = {};

export const Optimistic: StoryObj<typeof OptimisticInputBubble> = {
  render: (args) => <OptimisticInputBubble {...args} />,
  args: {
    buffer: {
      id: "optimistic:buffer-1",
      sessionId: "session-1",
      content: "This message is being sent.",
      attachments: [],
      metadata: { source: "web" },
      createdAt: "2026-05-19T00:00:00Z",
      status: "sending",
    },
  },
};

export const WithAttachment: Story = {
  args: {
    buffer: {
      id: "buffer-2",
      sessionId: "session-1",
      content: "Please inspect this file before answering.",
      attachments: ["exchange://exchange/story/files/pending/original"],
      metadata: { source: "web" },
      createdAt: "2026-05-19T00:00:00Z",
      status: "pending",
    },
  },
};

export const WithSkillAction: Story = {
  args: {
    buffer: {
      id: "buffer-4",
      sessionId: "session-1",
      content: "Review the current diff and commit required fixes.",
      action: {
        type: "skill",
        skill_path: "/workspace/agent/app/.claude/skills/code-review/SKILL.md",
      },
      attachments: [],
      metadata: { source: "web" },
      createdAt: "2026-05-19T00:00:00Z",
      status: "pending",
    },
  },
};

export const Deleting: Story = {
  args: {
    buffer: {
      id: "buffer-3",
      sessionId: "session-1",
      content: "Remove this before the next model turn.",
      attachments: [],
      metadata: { source: "web" },
      createdAt: "2026-05-19T00:00:00Z",
      status: "deleting",
    },
  },
};
