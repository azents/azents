import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { OptimisticInputBubble } from "./OptimisticInputBubble";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  tags: ["ci-contract"],
  title: "chat/OptimisticInputBubble",
  component: OptimisticInputBubble,
  args: {
    buffer: {
      id: "buffer-story",
      sessionId: "session-story",
      content: "Review this report.",
      attachments: [],
      metadata: { source: "web" },
      createdAt: "2026-10-16T00:00:00Z",
      status: "sending",
      requestedInferenceProfile: {
        model_target_label: "quality",
        reasoning_effort: null,
        enabled_execution_options: [],
      },
    },
    currentWorkspaceProfile: { userId: "user-story", name: "Story User" },
  },
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof OptimisticInputBubble>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Sending: Story = {};
export const PendingAttachment: Story = {
  args: {
    buffer: {
      ...meta.args.buffer,
      attachments: ["exchange://exchange/story/files/pending/original"],
    },
  },
};
