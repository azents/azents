import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { createChatMessage } from "../story-fixtures";
import { SubagentBlock } from "./SubagentBlock";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const openDetails = (): void => {};

const subagentMessage = createChatMessage({
  id: "subagent-start-001",
  role: "subagent_start",
  content: null,
  createdAt: "2026-04-30T09:14:45.000Z",
  metadata: {
    subagent_name: "Review Subagent",
  },
});

const meta = {
  component: SubagentBlock,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof SubagentBlock>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Running = {
  args: {
    message: subagentMessage,
    isRunning: true,
    resultText: null,
    onClick: openDetails,
  },
} satisfies Story;

export const Completed = {
  args: {
    message: subagentMessage,
    isRunning: false,
    resultText:
      "Reviewed the Storybook setup and found that providers are configured consistently.",
    onClick: openDetails,
  },
} satisfies Story;
