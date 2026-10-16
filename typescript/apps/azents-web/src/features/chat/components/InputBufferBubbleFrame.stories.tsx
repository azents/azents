import { Button } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { InputBufferBubbleFrame } from "./InputBufferBubbleFrame";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "chat/InputBufferBubbleFrame",
  component: InputBufferBubbleFrame,
  args: {
    content: "Review the latest changes and summarize the risks.",
    attachments: [],
    opacity: 0.6,
    actions: (
      <Button size="compact-xs" variant="subtle">
        Cancel
      </Button>
    ),
  },
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof InputBufferBubbleFrame>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Text: Story = {};
export const Goal: Story = {
  args: { action: { type: "goal" }, content: "Prepare a verified report." },
};
export const Attachment: Story = {
  args: { attachments: ["exchange://exchange/story/files/pending/original"] },
};
