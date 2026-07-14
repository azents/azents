import { expect, within } from "storybook/test";
import { AgentRunIndicator } from "./AgentRunIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Chat/AgentRunIndicator",
  component: AgentRunIndicator,
  parameters: { layout: "centered" },
} satisfies Meta<typeof AgentRunIndicator>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Starting: Story = {
  args: {
    modelCallStartedAt: new Date(Date.now() - 5_000).toISOString(),
  },
};

export const LongRunning: Story = {
  args: {
    modelCallStartedAt: new Date(Date.now() - 12_000).toISOString(),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/^\d+s$/)).toBeVisible();
  },
};
