import { fn } from "storybook/test";
import { BrowserKeyboardToolbar } from "./BrowserKeyboardToolbar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: BrowserKeyboardToolbar,
  parameters: { layout: "fullscreen" },
  args: {
    viewport: null,
    appearance: "bar",
    onPaste: fn(),
    onOpen: fn(),
  },
} satisfies Meta<typeof BrowserKeyboardToolbar>;
export default meta;
type Story = StoryObj<typeof meta>;

export const ContinuousToolbar = {} satisfies Story;
export const FloatingActions = {
  args: { appearance: "floating" },
} satisfies Story;
