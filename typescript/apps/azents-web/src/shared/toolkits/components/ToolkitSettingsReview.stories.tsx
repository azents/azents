import { expect, within } from "storybook/test";
import { ToolkitSettingsReview } from "./ToolkitSettingsReview";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Guided setup/Review",
  component: ToolkitSettingsReview,
  args: {
    provider: "AWS",
    name: "Cloud reports",
    ownership: "workspace",
    enabled: true,
    alwaysExposeTools: false,
  },
} satisfies Meta<typeof ToolkitSettingsReview>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Shared: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("region", { name: "Settings to save" }),
    ).toBeVisible();
    await expect(canvas.getByText(/Workspace shared/)).toBeVisible();
    await expect(canvas.getByText(/Credentials are not shown/)).toBeVisible();
  },
};
export const AgentDisabled: Story = {
  args: { ownership: "agent", enabled: false, alwaysExposeTools: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Only this Agent")).toBeVisible();
    await expect(canvas.getByText("Disabled")).toBeVisible();
    await expect(canvas.getByText("Always expose tools")).toBeVisible();
  },
};
export const DefaultName: Story = { args: { name: "" } };
export const Personal: Story = {
  args: { ownership: "user" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText(
        "Personal — only your personal Sessions with allowed Agents",
      ),
    ).toBeVisible();
  },
};
