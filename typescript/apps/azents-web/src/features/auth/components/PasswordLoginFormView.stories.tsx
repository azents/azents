import { expect, fn, userEvent, within } from "storybook/test";
import { PasswordLoginFormView } from "./PasswordLoginStep";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: PasswordLoginFormView,
  tags: ["ci-contract"],
  args: {
    email: "alex@example.com",
    error: null,
    isPending: false,
    password: "",
    formRef: { current: null },
    syncPasswordState: fn(),
    handleSubmit: fn((event: React.FormEvent<HTMLFormElement>) =>
      event.preventDefault(),
    ),
    onSubmit: fn(),
    onUseOtherMethod: fn(),
  },
} satisfies Meta<typeof PasswordLoginFormView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: "Log in",
      }),
    ).toBeDisabled();
  },
} satisfies Story;
export const Ready = {
  args: { password: "entered" },
  play: async ({ args, canvasElement }) => {
    await userEvent.type(
      within(canvasElement).getByPlaceholderText("Password"),
      "entered",
    );
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Log in",
      }),
    );
    await expect(args.handleSubmit).toHaveBeenCalledOnce();
  },
} satisfies Story;
export const Error = {
  args: { error: "The password you entered is incorrect" },
} satisfies Story;
export const Submitting = {
  args: { isPending: true, password: "entered" },
} satisfies Story;
