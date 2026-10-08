import { expect, fn, userEvent, within } from "storybook/test";
import { RuntimeWebAuth } from "./RuntimeWebAuth";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: RuntimeWebAuth,
  args: {
    serviceId: "01a0a4dfd3fb7b88b7ecf202d86f3bd3",
    mainWebOrigin: "https://web.example.com",
    returnTarget: "/",
    state: { type: "CHECKING" },
    onRetry: fn(),
  },
} satisfies Meta<typeof RuntimeWebAuth>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Checking = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "Connecting to this web service" }),
    ).toBeVisible();
    await expect(
      canvas.queryByRole("button", { name: "Try again" }),
    ).toBeNull();
  },
} satisfies Story;

export const Error = {
  args: { state: { type: "ERROR", message: "Authentication required" } },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Authentication required")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Try again" }));
    await expect(args.onRetry).toHaveBeenCalledOnce();
  },
} satisfies Story;
