import { expect, fn, userEvent, within } from "storybook/test";
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

export const PendingInputDisablesEdit = {
  args: { appearance: "floating", editDisabled: true, onOpen: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const edit = canvas.getByRole("button", { name: "Edit" });
    await expect(edit).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Paste" })).toBeEnabled();
    await userEvent.click(edit);
    await expect(args.onOpen).not.toHaveBeenCalled();
  },
} satisfies Story;
