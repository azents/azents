import { expect, waitFor } from "storybook/test";
import { expectReadableContrast } from "@/shared/storybook/contrast";
import { ChatHumanMessageBody } from "./ChatHumanMessageBody";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Chat/Human Message Body",
  component: ChatHumanMessageBody,
  tags: ["ci-contract"],
  args: { children: "Human message with a theme-owned readable foreground." },
  parameters: { a11y: { test: "error" } },
} satisfies Meta<typeof ChatHumanMessageBody>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {
  globals: { colorScheme: "light" },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      const bubble = canvasElement.querySelector(".mantine-Paper-root");
      await expect(bubble).not.toBeNull();
      if (bubble != null) {
        await expectReadableContrast(bubble);
      }
    });
  },
};
export const Dark: Story = {
  ...Light,
  globals: { colorScheme: "dark" },
};
