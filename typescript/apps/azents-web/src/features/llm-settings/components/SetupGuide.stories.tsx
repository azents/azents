import { rem } from "@mantine/core";
import { expect, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { SetupGuide } from "./SetupGuide";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: SetupGuide,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(640)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    credType: "api_key",
    provider: "openai",
  },
} satisfies Meta<typeof SetupGuide>;

export default meta;

type Story = StoryObj<typeof meta>;

export const GenericApiKey = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Setup guide" }));
    await expect(
      canvas.getByText(
        "Go to the provider's dashboard, create an API key, and paste it above.",
      ),
    ).toBeVisible();
  },
} satisfies Story;

export const XaiApiKey = {
  args: {
    provider: "xai",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Setup guide" }));
    await expect(canvas.getByText(/developer API billing/i)).toBeVisible();
    await expect(canvas.getByText(/SuperGrok.*X Premium/i)).toBeVisible();
  },
} satisfies Story;
