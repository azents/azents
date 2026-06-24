import { LoginStep } from "./LoginStep";
import type { LoginState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const submitEmail = (): void => {};
const requestSignupEmail = (): void => {};

const meta = {
  component: LoginStep,
} satisfies Meta<typeof LoginStep>;

export default meta;

type Story = StoryObj<typeof meta>;

const idleState: LoginState = { type: "IDLE", error: null };

export const Idle = {
  args: {
    state: idleState,
    signupEmailAvailable: true,
    signupEmailSent: false,
    onRequestSignupEmail: requestSignupEmail,
    onSubmit: submitEmail,
  },
} satisfies Story;

export const WithError = {
  args: {
    state: { type: "IDLE", error: "Email delivery is temporarily unavailable" },
    signupEmailAvailable: true,
    signupEmailSent: false,
    onRequestSignupEmail: requestSignupEmail,
    onSubmit: submitEmail,
  },
} satisfies Story;

export const CheckingMethods = {
  args: {
    state: { type: "CHECKING_METHODS" },
    signupEmailAvailable: true,
    signupEmailSent: false,
    onRequestSignupEmail: requestSignupEmail,
    onSubmit: submitEmail,
  },
} satisfies Story;

export const SendingCode = {
  args: {
    state: { type: "SENDING" },
    signupEmailAvailable: true,
    signupEmailSent: false,
    onRequestSignupEmail: requestSignupEmail,
    onSubmit: submitEmail,
  },
} satisfies Story;
