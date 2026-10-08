import { Box, rem } from "@mantine/core";
import { expect, within } from "storybook/test";
import { ToolInputContent } from "./ToolInputContent";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = { component: ToolInputContent } satisfies Meta<
  typeof ToolInputContent
>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ObjectFields = {
  args: {
    input: JSON.stringify({
      command: "printf 'hello'\nprintf 'world'",
      workdir: "/workspace/example",
      enabled: false,
      limit: 0,
      option: null,
      empty: "",
      nested: { files: ["a.ts", "b.ts"] },
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("term")).toHaveLength(7);
    await expect(canvas.getByText("command")).toBeVisible();
    await expect(canvas.getByText(/printf 'hello'/)).toHaveTextContent(
      "printf 'hello' printf 'world'",
    );
    await expect(canvas.getByText("false")).toBeVisible();
    await expect(canvas.getByText("0")).toBeVisible();
    await expect(canvas.getByText("null")).toBeVisible();
    await expect(canvas.getByText('""')).toBeVisible();
    await expect(canvas.getByText(/"files":/)).toBeVisible();
  },
} satisfies Story;

export const EmptyObject = {
  args: { input: "{}" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("{}")).toBeVisible();
  },
} satisfies Story;

export const Freeform = {
  args: { input: "*** Begin Patch\n*** End Patch" },
} satisfies Story;

export const PartialJson = {
  args: { input: '{"command":' },
} satisfies Story;

export const LongMobileInput = {
  decorators: [
    (Story) => (
      <Box w={rem(340)} maw="100%">
        <Story />
      </Box>
    ),
  ],
  args: {
    input: JSON.stringify({
      ["long_field_name_".repeat(8)]: "unbroken_value_".repeat(100),
      content: Array.from({ length: 60 }, (_, i) => `line ${i}`).join("\n"),
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getAllByRole("term")).toHaveLength(2);
    const bounds = canvasElement.getBoundingClientRect();
    for (const code of canvasElement.querySelectorAll("pre")) {
      await expect(code.getBoundingClientRect().right).toBeLessThanOrEqual(
        bounds.right + 1,
      );
    }
  },
} satisfies Story;
