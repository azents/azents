import { useForm } from "@mantine/form";
import { useTranslations } from "next-intl";
import { fn } from "storybook/test";
import { WorkspaceCreateFormInnerView } from "./WorkspaceCreateForm";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
function Fixture({
  error,
  isPending,
  invalid,
}: {
  error: string | null;
  isPending: boolean;
  invalid: boolean;
}): React.ReactElement {
  const t = useTranslations("workspaces");
  const form = useForm({
    initialValues: {
      workspaceName: "Preview Workspace",
      workspaceHandle: "preview",
      ownerName: "Preview Owner",
    },
    initialErrors: invalid
      ? { workspaceHandle: "Use lowercase letters, numbers and hyphens." }
      : {},
    validate: (): Record<string, string> => ({}),
  });
  return (
    <WorkspaceCreateFormInnerView
      t={t}
      form={form}
      error={error}
      isPending={isPending}
      onSubmit={fn()}
      handleSubmit={fn()}
      handleNameChange={fn()}
      handleHandleChange={fn()}
    />
  );
}
const meta = {
  tags: ["ci-contract"],
  component: Fixture,
  args: { error: null, isPending: false, invalid: false },
} satisfies Meta<typeof Fixture>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Ready = {} satisfies Story;
export const ValidationError = { args: { invalid: true } } satisfies Story;
export const ServerError = {
  args: { error: "This workspace handle is unavailable." },
} satisfies Story;
export const Creating = { args: { isPending: true } } satisfies Story;
