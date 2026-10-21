import { useTranslations } from "next-intl";
import { expect, fn, within } from "storybook/test";
import { SignupFormView, SignupView } from "./SignupView";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function FormFixture({
  ready = false,
  submitting = false,
  error = null,
}: {
  ready?: boolean;
  submitting?: boolean;
  error?: string | null;
}): React.ReactElement {
  const t = useTranslations("auth.signup");
  return (
    <SignupFormView
      emailHint="preview@example.invalid"
      email={ready ? "preview@example.invalid" : ""}
      password={ready ? "preview-password" : ""}
      setEmail={fn()}
      setPassword={fn()}
      t={t}
      error={error}
      submitting={submitting}
      onSubmit={fn()}
      handleSubmit={(event): void => event.preventDefault()}
    />
  );
}
const meta = {
  tags: ["ci-contract"],
  component: SignupView,
  args: { state: { type: "LOADING" }, onSubmit: fn() },
} satisfies Meta<typeof SignupView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Loading = {} satisfies Story;
export const Invalid = {
  args: { state: { type: "INVALID", message: "This invitation has expired." } },
} satisfies Story;
export const Error = {
  args: { state: { type: "ERROR", message: "Unable to load invitation." } },
} satisfies Story;
export const Success = { args: { state: { type: "SUCCESS" } } } satisfies Story;
export const EmptyForm = { render: () => <FormFixture /> } satisfies Story;
export const ReadyForm = {
  render: () => <FormFixture ready />,
} satisfies Story;
export const FormError = {
  render: () => <FormFixture ready error="Unable to create account." />,
} satisfies Story;
export const Submitting = {
  render: () => <FormFixture ready submitting />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText("Email")).toBeDisabled();
  },
} satisfies Story;
