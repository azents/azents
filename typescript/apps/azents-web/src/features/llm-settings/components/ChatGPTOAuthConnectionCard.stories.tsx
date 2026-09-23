import { expect, fn, userEvent, within } from "storybook/test";
import { ChatGPTOAuthConnectionCard } from "./ChatGPTOAuthConnectionCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ChatGPTOAuthConnectionCard,
  args: {
    canManage: true,
    state: { type: "IDLE" },
    starting: false,
    cancelling: false,
    onStart: fn(),
    onCancel: fn(),
  },
} satisfies Meta<typeof ChatGPTOAuthConnectionCard>;

export default meta;
type Story = StoryObj<typeof meta>;

export const Idle = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect with device code" }),
    );
    await expect(args.onStart).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Reauthenticate = {
  args: { integrationId: "chatgpt-existing" },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "Reauthenticate with device code",
      }),
    ).toBeVisible();
  },
} satisfies Story;

export const Pending = {
  args: {
    state: {
      type: "PENDING",
      sessionId: "chatgpt-device-session",
      userCode: "ABCD-EFGH",
      verificationUri: "https://auth.openai.com/codex/device",
      intervalMs: 5_000,
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ABCD-EFGH")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await expect(args.onCancel).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Connected = {
  args: { state: { type: "CONNECTED" } },
} satisfies Story;

export const Error = {
  args: { state: { type: "ERROR", message: "Device authorization failed." } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("Device authorization failed."),
    ).toBeVisible();
  },
} satisfies Story;

export const ReadOnly = {
  args: { canManage: false },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("button", {
        name: "Connect with device code",
      }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
