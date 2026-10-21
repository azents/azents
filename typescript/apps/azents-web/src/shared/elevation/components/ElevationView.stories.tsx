import { fn } from "storybook/test";
import { ElevationView } from "./ElevationView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: ElevationView,
  tags: ["ci-contract"],
  args: {
    state: { type: "CHOOSE_METHOD", methods: [] },
    onSelectEmail: fn(),
    onSelectPassword: fn(),
    onSubmitEmailCode: fn(),
    onSubmitPassword: fn(),
    onResendCode: fn(),
  },
} satisfies Meta<typeof ElevationView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const ChooseMethod = {} satisfies Story;
export const SendingCode = {
  args: { state: { type: "EMAIL_SENDING" } },
} satisfies Story;
export const Password = {
  args: { state: { type: "PASSWORD_INPUT", error: null } },
} satisfies Story;
export const PasswordError = {
  args: { state: { type: "PASSWORD_INPUT", error: "Incorrect password." } },
} satisfies Story;
export const PasswordVerifying = {
  args: { state: { type: "PASSWORD_VERIFYING" } },
} satisfies Story;
