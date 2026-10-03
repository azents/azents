import { rem } from "@mantine/core";
import { useForm } from "@mantine/form";
import { expect, fn, userEvent, within } from "storybook/test";
import {
  resolveDefaultToolkitSlug,
  trimToolkitWhitespace,
} from "@/shared/lib/toolkit-identifiers";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { projectToolkitConfig } from "../toolkit-config-projection";
import { ToolkitForm } from "./ToolkitForm";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitFormProps } from "./ToolkitForm";
import type { ToolkitConfigResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

type ToolkitFormStoryProps = Omit<
  ToolkitFormProps,
  "form" | "onSubmit" | "configProjection"
> & {
  onSubmitValues?: (values: ToolkitFormValues) => void;
};

function ToolkitFormStory(props: ToolkitFormStoryProps): ReactElement {
  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: props.currentToolSlug,
      slug: props.formState.type === "EDIT" ? props.formState.config.slug : "",
      name: props.formState.type === "EDIT" ? props.formState.config.name : "",
      description: "Read-only shell access for workspace diagnostics.",
      prompt: "Use the available shell tools for diagnostics.",
      config:
        props.formState.type === "EDIT"
          ? props.formState.config.config
          : { allowed_domains: [], denied_domains: [] },
      credentials: null,
      enabled: true,
      alwaysExposeTools: false,
    },
  });
  const canonicalName =
    props.toolOptions.find((option) => option.value === props.currentToolSlug)
      ?.label ?? props.namePlaceholder;

  return (
    <ToolkitForm
      {...props}
      slugPlaceholder={
        canonicalName
          ? resolveDefaultToolkitSlug(
              trimToolkitWhitespace(form.values.name) || canonicalName,
              canonicalName,
            )
          : props.slugPlaceholder
      }
      configProjection={projectToolkitConfig(
        props.currentToolSlug,
        form.values.config,
      )}
      configurationFields={null}
      form={form}
      onSubmit={form.onSubmit((values) => {
        props.onSubmitValues?.(values);
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
    await expect(
      canvas.getByRole("textbox", { name: "Name" }),
    ).not.toBeRequired();
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
    await expect(canvas.getByRole("textbox", { name: "Name" })).toBeRequired();
    await expect(canvas.getByRole("textbox", { name: "Name" })).toHaveAttribute(
      "placeholder",
      "Enter a name for this MCP connection",
    );
    await expect(canvas.getByLabelText("Slug")).not.toBeRequired();
    await expect(canvas.getByLabelText("Slug")).toHaveAttribute(
      "placeholder",
      "mcp",
    );
    await userEvent.type(
      canvas.getByRole("textbox", { name: "Name" }),
      "Production MCP",
    );
    await expect(canvas.getByLabelText("Slug")).toHaveAttribute(
      "placeholder",
      "production_mcp",
    );
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

const editedConfig: ToolkitConfigResponse = {
  id: "toolkit-story",
  workspace_id: "workspace-story",
  toolkit_type: "mcp",
  slug: "production_mcp",
  name: "Production MCP",
  description: "A saved service connection.",
  config: { server_url: "https://mcp.example", auth_type: "oauth2" },
  prompt: null,
  enabled: true,
  always_expose_tools: false,
  has_credentials: true,
  created_at: "2026-05-01T00:00:00Z",
  updated_at: "2026-05-01T00:00:00Z",
};

export const Editing = {
  args: {
    formState: { type: "EDIT", config: editedConfig },
    isEdit: true,
    currentToolSlug: "mcp",
    toolOptions: [{ value: "mcp", label: "MCP" }],
    toolkitTypeLocked: true,
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText("Name")).toHaveValue("Production MCP");
    await expect(canvas.getByRole("combobox", { name: "Tool" })).toBeDisabled();
  },
} satisfies Story;

export const Submitting = {
  args: { mutationState: { type: "SUBMITTING" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Add" }),
    ).toHaveAttribute("data-loading", "true");
  },
} satisfies Story;

export const OAuthNotConnected = {
  args: { ...Editing.args, showOauthConnection: true, onConnectOauth: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Not connected")).toBeVisible();
    await expect(canvas.queryByText("not_connected")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Connect" }));
    await expect(args.onConnectOauth).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const OAuthConnected = {
  args: {
    ...Editing.args,
    showOauthConnection: true,
    formState: {
      type: "EDIT",
      config: { ...editedConfig, oauth_connection: { status: "connected" } },
    },
    onDisconnectOauth: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Connected")).toBeVisible();
    await userEvent.click(canvas.getByRole("button", { name: "Disconnect" }));
    await expect(args.onDisconnectOauth).toHaveBeenCalledTimes(1);
  },
} satisfies Story;

export const OAuthReconnectRequired = {
  args: {
    ...OAuthConnected.args,
    formState: {
      type: "EDIT",
      config: {
        ...editedConfig,
        oauth_connection: { status: "reconnect_required" },
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Reconnect required")).toBeVisible();
    await expect(
      canvas.queryByText("reconnect_required"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const OAuthPending = {
  args: {
    ...OAuthConnected.args,
    oauthConnectionPending: { connect: true, disconnect: false },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Reconnect" }),
    ).toHaveAttribute("data-loading", "true");
  },
} satisfies Story;

export const CancelDelegatesWithoutSubmission = {
  args: { onCancel: fn(), onSubmitValues: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", { name: "Cancel" }),
    );
    await expect(args.onCancel).toHaveBeenCalledTimes(1);
    await expect(args.onSubmitValues).not.toHaveBeenCalled();
    await expect(
      within(canvasElement).getByRole("button", { name: "Add" }),
    ).not.toHaveAttribute("data-loading");
  },
} satisfies Story;
