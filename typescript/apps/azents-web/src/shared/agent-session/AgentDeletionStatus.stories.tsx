import { Stack } from "@mantine/core";
import { expect, within } from "storybook/test";
import { AgentDeletionBadge, AgentDeletionNotice } from "./AgentDeletionStatus";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: AgentDeletionBadge,
  tags: ["ci-contract"],
  render: (args) => (
    <Stack>
      <AgentDeletionBadge {...args} />
      <AgentDeletionNotice {...args} />
    </Stack>
  ),
} satisfies Meta<typeof AgentDeletionBadge>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Active = {
  args: { status: null },
} satisfies Story;

export const Deleting = {
  args: { status: "deleting" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("status")).toBeVisible();
  },
} satisfies Story;

export const DeletionError = {
  args: { status: "deletion_error" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("status")).toBeVisible();
  },
} satisfies Story;
