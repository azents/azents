import { useTranslations } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import { PasswordFormView } from "./PasswordForm";
import type { PasswordFormViewProps } from "../containers/usePasswordFormController";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

function Fixture(props: Omit<PasswordFormViewProps, "t">): React.ReactElement {
  const t = useTranslations("security");
  return <PasswordFormView {...props} t={t} />;
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: {
    hasPassword: false,
    state: { type: "IDLE", error: null },
    password: "",
    confirmPassword: "",
    setPassword: fn(),
    setConfirmPassword: fn(),
    setLocalError: fn(),
    handleSubmit: fn((event: React.FormEvent): void => event.preventDefault()),
    error: null,
  },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Empty = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Set password" }),
    ).toBeDisabled();
  },
} satisfies Story;
export const Ready = {
  args: {
    password: "preview-only-password",
    confirmPassword: "preview-only-password",
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Set password" }),
    );
    await expect(args.handleSubmit).toHaveBeenCalled();
  },
} satisfies Story;
export const ChangePassword = { args: { hasPassword: true } } satisfies Story;
export const Error = {
  args: { error: "Passwords do not match." },
} satisfies Story;
export const Saving = {
  args: {
    state: { type: "SAVING" },
    password: "preview-only-password",
    confirmPassword: "preview-only-password",
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByLabelText("Password", { exact: true }),
    ).toBeDisabled();
  },
} satisfies Story;
