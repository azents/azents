import { rem } from "@mantine/core";
import { useForm } from "@mantine/form";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ToolkitForm } from "./ToolkitForm";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitFormProps } from "./ToolkitForm";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

type ToolkitFormStoryProps = Omit<ToolkitFormProps, "form" | "onSubmit">;

function ToolkitFormStory(props: ToolkitFormStoryProps): ReactElement {
  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: props.currentToolSlug,
      slug: "",
      name: "",
      description: "Read-only shell access for workspace diagnostics.",
      prompt: "Use the available shell tools for diagnostics.",
      config: { allowed_domains: [], denied_domains: [] },
      credentials: null,
      enabled: true,
      alwaysExposeTools: false,
    },
  });

  return (
    <ToolkitForm
      {...props}
      form={form}
      onSubmit={form.onSubmit((values) => {
        void values;
      })}
    />
  );
}

const meta = {
  component: ToolkitFormStory,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(760)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    handle: "acme",
    embedded: false,
    toolkitTypeLocked: false,
    formState: { type: "CREATE" },
    mutationState: { type: "IDLE", error: null },
    scopeListState: { type: "READY", scopes: [] },
    isEdit: false,
    backPath: "/w/acme/toolkits",
    toolOptions: [{ value: "shell", label: "Shell" }],
    currentToolSlug: "shell",
    namePlaceholder: "Shell",
    slugPlaceholder: "shell",
    nameRequired: false,
    showOauthConnection: false,
    oauthConnectionPending: { connect: false, disconnect: false },
    onToolSelect: () => {},
    onConfigChange: () => {},
    onCredentialsChange: () => {},
    onConnectOauth: () => {},
    onDisconnectOauth: () => {},
    onAddScope: () => {},
    onDeleteScope: () => {},
    onCancel: () => {},
  },
} satisfies Meta<typeof ToolkitFormStory>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Create = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Name")).toHaveAttribute(
      "placeholder",
      "Shell",
    );
    await expect(canvas.getByLabelText("Slug")).toHaveAttribute(
      "placeholder",
      "shell",
    );
  },
} satisfies Story;

export const GenericMcpRequiresName = {
  args: {
    currentToolSlug: "mcp",
    toolOptions: [{ value: "mcp", label: "MCP" }],
    namePlaceholder: "",
    slugPlaceholder: "mcp",
    nameRequired: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Name")).toBeRequired();
    await expect(canvas.getByLabelText("Name")).toHaveAttribute(
      "placeholder",
      "Enter a name for this MCP connection",
    );
    await expect(canvas.getByLabelText("Slug")).not.toBeRequired();
  },
} satisfies Story;

export const Loading = {
  args: {
    formState: { type: "LOADING" },
  },
} satisfies Story;

export const NotFound = {
  args: {
    formState: { type: "NOT_FOUND" },
  },
} satisfies Story;

export const MutationError = {
  args: {
    mutationState: { type: "IDLE", error: "Toolkit configuration failed." },
  },
} satisfies Story;
