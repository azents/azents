import { expect, fn, userEvent, within } from "storybook/test";
import { LoginStep } from "./LoginStep";
import type { LoginState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const submitEmail = (): void => {};
const requestSignupEmail = (): void => {};

const meta = {
  component: LoginStep,
  args: {
    emailAvailable: true,
  },
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
    onSubmit: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByText("We'll send you a verification code"),
    ).toBeVisible();
    await expect(canvas.queryByLabelText(/^Password/)).not.toBeInTheDocument();
    await userEvent.type(canvas.getByRole("textbox"), "user@example.com");
    await userEvent.click(canvas.getByRole("button", { name: "Continue" }));
    await expect(args.onSubmit).toHaveBeenCalledWith("user@example.com", "");
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

export const PasswordOnly = {
  args: {
    state: idleState,
    emailAvailable: false,
    signupEmailAvailable: false,
    signupEmailSent: false,
    onRequestSignupEmail: fn(),
    onSubmit: fn(),
  },
  play: async ({ args, canvasElement }) => {
    const canvas = within(canvasElement);
    const email = canvas.getByRole("textbox", { name: "Email" });
    const password = canvas.getByLabelText(/^Password/);
    const submit = canvas.getByRole("button", { name: "Log in" });
    await expect(
      canvas.queryByText("We'll send you a verification code"),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Request signup link" }),
    ).not.toBeInTheDocument();
    await expect(email).toHaveAttribute("autocomplete", "username");
    await expect(password).toHaveAttribute("autocomplete", "current-password");
    await expect(submit).toBeDisabled();
    await userEvent.type(email, "user@example.com");
    await expect(submit).toBeDisabled();
    await userEvent.type(password, "test-password");
    await expect(submit).toBeEnabled();
    await userEvent.keyboard("{Enter}");
    await expect(args.onSubmit).toHaveBeenCalledWith(
      "user@example.com",
      "test-password",
    );
    await expect(args.onRequestSignupEmail).not.toHaveBeenCalled();
  },
} satisfies Story;

export const PasswordError = {
  args: {
    ...PasswordOnly.args,
    state: { type: "IDLE", error: "Invalid email or password." },
  },
} satisfies Story;

export const PasswordSubmitting = {
  args: {
    ...PasswordOnly.args,
    state: { type: "SUBMITTING" },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("textbox", { name: "Email" })).toBeDisabled();
    await expect(canvas.getByLabelText(/^Password/)).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Log in" })).toBeDisabled();
  },
} satisfies Story;
