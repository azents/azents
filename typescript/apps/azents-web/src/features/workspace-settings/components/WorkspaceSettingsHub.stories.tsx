import { rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { WorkspaceSettingsHub } from "./WorkspaceSettingsHub";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: WorkspaceSettingsHub,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(920)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "platform-engineering",
  },
} satisfies Meta<typeof WorkspaceSettingsHub>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Default models")).toBeVisible();
    await expect(canvas.getByText("LLM integrations")).toBeVisible();
    await expect(canvas.getByText("Runtime profiles")).toBeVisible();
  },
} satisfies Story;
