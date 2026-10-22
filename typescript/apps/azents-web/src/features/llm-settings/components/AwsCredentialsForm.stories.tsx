import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { expect, fn, within } from "storybook/test";
import { AwsCredentialsFormView } from "./AwsCredentialsForm";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture({
  isCreate,
  isSubmitting,
}: {
  isCreate: boolean;
  isSubmitting: boolean;
}): React.ReactElement {
  const t = useTranslations("workspace.llmSettings");
  const form = useForm({
    initialValues: {
      accessKeyId: isCreate ? "" : "PREVIEW_ACCESS_KEY",
      secretAccessKey: "",
      region: isCreate ? "" : "us-east-1",
      roleArn: "",
    },
  });
  return (
    <AwsCredentialsFormView
      t={t}
      form={form}
      isCreate={isCreate}
      isSubmitting={isSubmitting}
      onClose={fn()}
      handleSubmit={fn()}
    />
  );
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: { isCreate: true, isSubmitting: false },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Create = {
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByLabelText(/Secret access key/i),
    ).toBeRequired();
  },
} satisfies Story;
export const Edit = {
  args: { isCreate: false },
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByLabelText(/Secret access key/i);
    await expect(input).toHaveValue("");
    await expect(input).not.toBeRequired();
    await expect(within(canvasElement).getByLabelText("Region")).toHaveValue(
      "us-east-1",
    );
  },
} satisfies Story;
export const Submitting = { args: { isSubmitting: true } } satisfies Story;
