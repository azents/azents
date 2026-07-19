import { expect, fn, userEvent, within } from "storybook/test";
import { KimiOAuthConnectionCard } from "./KimiOAuthConnectionCard";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: KimiOAuthConnectionCard,
  args: {
    canManage: true,
    connectionStatus: null,
    reconnect: false,
    state: { type: "IDLE" },
    starting: false,
    cancelling: false,
    onStart: fn(),
    onCancel: fn(),
  },
} satisfies Meta<typeof KimiOAuthConnectionCard>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Idle = {
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Kimi subscription")).toBeVisible();
    await expect(
      canvas.getByText(
        "Available models and quota depend on your Kimi subscription entitlement.",
      ),
    ).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Connect Kimi subscription" }),
    );
    await expect(args.onStart).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Pending = {
  args: {
    state: {
      type: "PENDING",
      sessionId: "kimi-session-1",
      userCode: "KIMI-2468",
      verificationUri: "https://auth.kimi.com/device",
      intervalMs: 5_000,
      expiresAt: "2026-07-20T20:00:00Z",
    },
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("KIMI-2468")).toBeVisible();
    await expect(
      canvas.getByRole("link", { name: "Open Kimi authorization page" }),
    ).toHaveAttribute("href", "https://auth.kimi.com/device");
    await userEvent.click(canvas.getByRole("button", { name: "Cancel" }));
    await expect(args.onCancel).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Connected = {
  args: {
    connectionStatus: "connected",
    reconnect: true,
    state: { type: "CONNECTED" },
  },
} satisfies Story;

export const ReconnectRequired = {
  args: {
    connectionStatus: "refresh_required",
    reconnect: true,
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Reconnect required")).toBeVisible();
    await userEvent.click(
      canvas.getByRole("button", { name: "Reconnect Kimi subscription" }),
    );
    await expect(args.onStart).toHaveBeenCalledOnce();
  },
} satisfies Story;

export const Expired = {
  args: {
    state: {
      type: "ERROR",
      message: "Device authorization expired.",
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Kimi connection failed")).toBeVisible();
    await expect(
      canvas.getByRole("button", { name: "Try again" }),
    ).toBeVisible();
  },
} satisfies Story;

export const ReadOnly = {
  args: {
    canManage: false,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.queryByRole("button", { name: "Connect Kimi subscription" }),
    ).not.toBeInTheDocument();
  },
} satisfies Story;
