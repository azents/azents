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
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("status")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Deleting")).not.toBeInTheDocument();
    await expect(canvas.queryByText("Deletion error")).not.toBeInTheDocument();
  },
} satisfies Story;

export const Deleting = {
  args: { status: "deleting" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Deleting", { exact: true })).toBeVisible();
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "This agent is being deleted. You can inspect it, but changes are unavailable.",
    );
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
} satisfies Story;

export const DeletionError = {
  args: { status: "deletion_error" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("Deletion error", { exact: true }),
    ).toBeVisible();
    await expect(canvas.getByRole("status")).toHaveTextContent(
      "Agent deletion encountered an error. You can inspect it, but changes remain unavailable.",
    );
    await expect(canvas.queryByRole("button")).not.toBeInTheDocument();
  },
} satisfies Story;
