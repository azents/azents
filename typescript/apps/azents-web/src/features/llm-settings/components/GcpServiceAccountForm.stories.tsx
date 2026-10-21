import { expect, fn, within } from "storybook/test";
import { GcpServiceAccountFormView } from "./GcpServiceAccountForm";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: GcpServiceAccountFormView,
  tags: ["ci-contract"],
  args: {
    name: "",
    provider: "vertex_ai",
    integration: null,
    isCreate: true,
    isSubmitting: false,
    onClose: fn(),
    onCreate: fn(),
    onUpdate: fn(),
    projectIdInput: { value: "", onChange: fn() },
    regionInput: { value: "", onChange: fn() },
    serviceAccountInput: { value: "", onChange: fn() },
    handleSubmit: fn((event?: React.FormEvent<HTMLFormElement>) =>
      event?.preventDefault(),
    ),
  },
} satisfies Meta<typeof GcpServiceAccountFormView>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Create = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const input of canvas.getAllByRole("textbox")) {
      await expect(input).toBeRequired();
    }
  },
} satisfies Story;
export const EditRedactedCredentials = {
  args: {
    isCreate: false,
    projectIdInput: { value: "my-project", onChange: fn() },
    regionInput: { value: "us-central1", onChange: fn() },
  },
} satisfies Story;
export const Submitting = { args: { isSubmitting: true } } satisfies Story;
