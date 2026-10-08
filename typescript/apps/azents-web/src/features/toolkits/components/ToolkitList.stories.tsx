import { expect, fn, userEvent, within } from "storybook/test";
import { ToolkitList } from "./ToolkitList";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: ToolkitList,
  args: {
    handle: "acme",
    listState: { type: "READY", configs: [] },
    deleteTarget: null,
    deleteState: { type: "IDLE" },
    onDelete: fn(),
    onToggleEnabled: fn(),
    onConfirmDelete: fn(),
    onCancelDelete: fn(),
  },
} satisfies Meta<typeof ToolkitList>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {} satisfies Story;
export const Loading = {
  args: { listState: { type: "LOADING" } },
} satisfies Story;
export const Error = { args: { listState: { type: "ERROR" } } } satisfies Story;
export const DeleteConfirmation = {
  args: { deleteTarget: "toolkit-1" },
} satisfies Story;
export const DeletePending = {
  args: { deleteTarget: "toolkit-1", deleteState: { type: "PENDING" } },
} satisfies Story;
export const LocalDeleteFailure = {
  args: {
    deleteTarget: "toolkit-1",
    deleteState: {
      type: "ERROR",
      message:
        "The local deletion request was interrupted. Check the saved Toolkit and try again.",
    },
  },
  play: async ({ canvasElement, args }) => {
    const page = within(canvasElement.ownerDocument.body);
    const dialog = within(await page.findByRole("dialog"));
    await expect(
      dialog.getByText(
        "The local deletion request was interrupted. Check the saved Toolkit and try again.",
      ),
    ).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await expect(args.onConfirmDelete).toHaveBeenCalled();
  },
} satisfies Story;
