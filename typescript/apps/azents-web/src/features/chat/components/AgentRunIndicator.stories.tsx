import { expect, within } from "storybook/test";
import { AgentRunIndicator } from "./AgentRunIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Chat/AgentRunIndicator",
  component: AgentRunIndicator,
  args: {
    modelCallStartedAt: new Date(Date.now() - 26_000).toISOString(),
  },
  parameters: { layout: "centered" },
} satisfies Meta<typeof AgentRunIndicator>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Running: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("status")).toBeVisible();
  },
};
