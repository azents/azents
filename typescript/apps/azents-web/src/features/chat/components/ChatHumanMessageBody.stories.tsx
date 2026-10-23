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
        <span
          data-background-reference
          style={{
            backgroundColor:
              "light-dark(var(--mantine-color-blue-6), var(--mantine-color-blue-8))",
          }}
        />
      </>
    ),
  ],
  parameters: { a11y: { test: "error" } },
} satisfies Meta<typeof ChatHumanMessageBody>;
export default meta;
type Story = StoryObj<typeof meta>;

async function assertMessagePalette(
  canvasElement: HTMLElement,
  mode: "light" | "dark",
): Promise<void> {
  await waitFor(async () => {
    await expect(canvasElement.ownerDocument.documentElement).toHaveAttribute(
      "data-mantine-color-scheme",
      mode,
    );
    const bubble = canvasElement.querySelector(".mantine-Paper-root");
    const text = canvasElement.querySelector("[data-message-text]");
    const reference = canvasElement.querySelector("[data-white-reference]");
    const background = canvasElement.querySelector(
      "[data-background-reference]",
    );
    if (
      bubble == null ||
      text == null ||
      reference == null ||
      background == null
    ) {
      throw new Error("Missing human message palette fixture");
    }
    const white = getComputedStyle(reference).color;
    await expect(getComputedStyle(bubble).color).toBe(white);
    await expect(getComputedStyle(text).color).toBe(white);
    await expect(getComputedStyle(bubble).backgroundColor).toBe(
      getComputedStyle(background).backgroundColor,
    );
    if (mode === "dark") {
      await expectReadableContrast(text, bubble);
    }
  });
}

export const Light: Story = {
  globals: { colorScheme: "light" },
  // The requested blue-6/white palette is explicit, not automatic AA contrast.
  parameters: {
    a11y: {
      config: { rules: [{ id: "color-contrast", enabled: false }] },
    },
  },
  play: async ({ canvasElement }) =>
    assertMessagePalette(canvasElement, "light"),
};
export const Dark: Story = {
  globals: { colorScheme: "dark" },
  play: async ({ canvasElement }) =>
    assertMessagePalette(canvasElement, "dark"),
};
