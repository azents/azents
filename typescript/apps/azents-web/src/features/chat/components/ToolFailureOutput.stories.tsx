import { Box, rem } from "@mantine/core";
import { expect } from "storybook/test";
import { ToolFailureOutput } from "./ToolFailureOutput";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ToolFailureOutput,
  decorators: [
    (Story) => (
      <Box w={rem(300)} maw="100%">
        <Story />
      </Box>
    ),
  ],
} satisfies Meta<typeof ToolFailureOutput>;
export default meta;
type Story = StoryObj<typeof meta>;

export const LongMultilineError = {
  args: {
    output:
      "Permission denied while writing the requested file. ".repeat(8) +
      "\n/workspace/" +
      "long-unbroken-path-".repeat(40) +
      "\nPlease check file permissions and try again.",
  },
  play: async ({ canvasElement }) => {
    const code = canvasElement.querySelector("pre");
    if (code === null) {
      throw new Error("Expected multiline tool failure output");
    }
    await expect(code).toHaveStyle({
      whiteSpace: "pre-wrap",
      overflowWrap: "anywhere",
    });
    await expect(code.scrollWidth).toBeLessThanOrEqual(code.clientWidth + 1);
    await expect(code.innerText).toContain("\n/workspace/");
    await expect(code.innerText).toContain("\nPlease check");
  },
} satisfies Story;

export const ShortError = {
  args: { output: "Connection refused." },
} satisfies Story;
