import { PasswordLoginStep } from "./PasswordLoginStep";
import type { PasswordLoginState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const submitPassword = (): void => {};
const useOtherMethod = (): void => {};

const meta = {
  component: PasswordLoginStep,
} satisfies Meta<typeof PasswordLoginStep>;

export default meta;

type Story = StoryObj<typeof meta>;

const idleState: PasswordLoginState = {
  type: "IDLE",
  email: "alex@example.com",
  error: null,
};

export const Idle = {
  args: {
    state: idleState,
    onSubmit: submitPassword,
    onUseOtherMethod: useOtherMethod,
  },
} satisfies Story;

export const WithError = {
  args: {
    state: {
      type: "IDLE",
      email: "alex@example.com",
      error: "The password you entered is incorrect",
    },
    onSubmit: submitPassword,
    onUseOtherMethod: useOtherMethod,
  },
} satisfies Story;

export const Submitting = {
  args: {
    state: { type: "SUBMITTING", email: "alex@example.com" },
    onSubmit: submitPassword,
    onUseOtherMethod: useOtherMethod,
  },
} satisfies Story;
