import { expect, fn, userEvent, within } from "storybook/test";
import { ToolkitDisconnectConfirmation } from "./ToolkitDisconnectConfirmation";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  title: "Toolkits/Shared Disconnect Confirmation",
  component: ToolkitDisconnectConfirmation,
  args: {
    personal: true,
    description: "Remove the saved connection.",
    detail: "Remote Provider consent may remain active.",
    confirmLabel: "Disconnect",
    cancelLabel: "Keep connection",
    pending: false,
    onConfirm: fn(),
    onCancel: fn(),
  },
} satisfies Meta<typeof ToolkitDisconnectConfirmation>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Personal: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText(/all allowed Agents in this Workspace/),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Keep connection" }),
    );
    await expect(args.onCancel).toHaveBeenCalled();
    await expect(args.onConfirm).not.toHaveBeenCalled();
  },
};
export const Shared: Story = { args: { personal: false } };
export const Disconnecting: Story = {
  args: { pending: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("button", { name: "Keep connection" }),
    ).toBeDisabled();
    await expect(
      canvas.getByRole("button", { name: "Disconnect" }),
    ).toBeDisabled();
  },
};
