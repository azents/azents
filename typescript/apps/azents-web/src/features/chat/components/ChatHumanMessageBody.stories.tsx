import { expect, waitFor } from "storybook/test";
import { expectReadableContrast } from "@/shared/storybook/contrast";
import { ChatHumanMessageBody } from "./ChatHumanMessageBody";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Chat/Human Message Body",
  component: ChatHumanMessageBody,
  tags: ["ci-contract"],
  args: {
    children: <span data-message-text>Human message with white text.</span>,
  },
  decorators: [
    (Story) => (
      <>
        <Story />
        <span
          data-white-reference
          style={{ color: "var(--mantine-color-white)" }}
        />
      </>
    ),
  ],
  parameters: { a11y: { test: "error" } },
} satisfies Meta<typeof ChatHumanMessageBody>;
export default meta;
type Story = StoryObj<typeof meta>;

export const Light: Story = {
  globals: { colorScheme: "light" },
  play: async ({ canvasElement }) => {
    await waitFor(async () => {
      const bubble = canvasElement.querySelector(".mantine-Paper-root");
      const text = canvasElement.querySelector("[data-message-text]");
      const reference = canvasElement.querySelector("[data-white-reference]");
      if (bubble == null || text == null || reference == null) {
        throw new Error("Missing human message contrast fixture");
      }
      const white = getComputedStyle(reference).color;
      await expect(getComputedStyle(bubble).color).toBe(white);
      await expect(getComputedStyle(text).color).toBe(white);
      await expectReadableContrast(text, bubble);
    });
  },
};
export const Dark: Story = {
  ...Light,
  globals: { colorScheme: "dark" },
};
