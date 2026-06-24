import { VerifyStep } from "./VerifyStep";
import type { VerifyState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const submitCode = (): void => {};
const resendCode = (): void => {};
const sentAt = new Date("2026-12-31T09:00:00.000Z").getTime();
const expiredSentAt = new Date("2026-04-30T09:00:00.000Z").getTime();

const meta = {
  component: VerifyStep,
} satisfies Meta<typeof VerifyStep>;

export default meta;

type Story = StoryObj<typeof meta>;

const idleState: VerifyState = {
  type: "IDLE",
  email: "alex@example.com",
  sentAt,
  error: null,
};

export const Idle = {
  args: {
    state: idleState,
    isResending: false,
    onSubmit: submitCode,
    onResend: resendCode,
  },
} satisfies Story;

export const WithError = {
  args: {
    state: {
      type: "IDLE",
      email: "alex@example.com",
      sentAt,
      error: "The verification code is invalid",
    },
    isResending: false,
    onSubmit: submitCode,
    onResend: resendCode,
  },
} satisfies Story;

export const Verifying = {
  args: {
    state: { type: "VERIFYING", email: "alex@example.com", sentAt },
    isResending: false,
    onSubmit: submitCode,
    onResend: resendCode,
  },
} satisfies Story;

export const Resending = {
  args: {
    state: idleState,
    isResending: true,
    onSubmit: submitCode,
    onResend: resendCode,
  },
} satisfies Story;

export const Expired = {
  args: {
    state: {
      type: "IDLE",
      email: "alex@example.com",
      sentAt: expiredSentAt,
      error: null,
    },
    isResending: false,
    onSubmit: submitCode,
    onResend: resendCode,
  },
} satisfies Story;
