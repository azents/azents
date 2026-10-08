import { Modal, rem, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { TRPCClientError } from "@trpc/client";
import { observable } from "@trpc/server/observable";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";
import {
  resolveDefaultToolkitSlug,
  trimToolkitWhitespace,
} from "@/shared/lib/toolkit-identifiers";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { trpc } from "@/trpc/client";
import { projectToolkitConfig } from "../toolkit-config-projection";
import { GithubConfigFields } from "./GithubConfigFields";
import { ToolkitForm } from "./ToolkitForm";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitFormProps } from "./ToolkitForm";
import type { ToolkitConfigResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement, ReactNode } from "react";

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
      description: `${props.namePlaceholder} configuration for workspace diagnostics.`,
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
      configurationFields={props.configurationFields ?? null}
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
    await expect(
      canvas.queryByRole("heading", { name: "Scopes" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByRole("button", { name: "Add workspace scope" }),
    ).not.toBeInTheDocument();
    await expect(
      canvas.queryByText("No scopes configured"),
    ).not.toBeInTheDocument();
  },
} satisfies Story;

export const Submitting = {
  args: { mutationState: { type: "SUBMITTING" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", { name: "Add" }),
    ).toHaveAttribute("data-loading", "true");
    await expect(
      within(canvasElement).getByRole("button", { name: "Cancel" }),
    ).toBeDisabled();
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
      config: {
        ...editedConfig,
        oauth_connection: { status: "connected", scope: "read:resources" },
      },
    },
    onDisconnectOauth: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Connected")).toBeVisible();
    await expect(canvas.getByText("Scope: read:resources")).toBeVisible();
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

function StaticGithubProvider({
  children,
}: {
  children: ReactNode;
}): ReactElement {
  const [queryClient] = useState(() => new QueryClient());
  const [client] = useState(() =>
    trpc.createClient({
      links: [
        () => () =>
          observable((observer) => {
            observer.error(
              new TRPCClientError(
                "Network operations are disabled in this static story.",
              ),
            );
          }),
      ],
    }),
  );
  return (
    <trpc.Provider client={client} queryClient={queryClient}>
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    </trpc.Provider>
  );
}

export const MobileEmbeddedGithub = {
  parameters: { testViewport: { width: 390, height: 844 } },
  decorators: [
    (Story) => (
      <StaticGithubProvider>
        <Modal
          opened
          onClose={() => {}}
          title="Toolkit settings"
          size="lg"
          centered
        >
          <Stack gap="md">
            <Story />
          </Stack>
        </Modal>
      </StaticGithubProvider>
    ),
  ],
  args: {
    embedded: true,
    agentId: "agent-1",
    toolkitTypeLocked: true,
    currentToolSlug: "github",
    toolOptions: [{ value: "github", label: "GitHub" }],
    namePlaceholder: "GitHub",
    slugPlaceholder: "github",
    configurationFields: (
      <GithubConfigFields
        config={{ github_auth_type: "pat" }}
        credentials={null}
        hasCredentials={false}
        authorizationState={null}
        onConfigChange={fn()}
        onCredentialsChange={fn()}
      />
    ),
  },
  play: async ({ canvasElement }) => {
    const body = within(canvasElement.ownerDocument.body);
    const dialog = body.getByRole("dialog", { name: "Toolkit settings" });
    await expect(
      within(dialog).getByRole("textbox", { name: "Name" }),
    ).toBeVisible();
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth);
    for (const element of dialog.querySelectorAll(
      ".mantine-Container-root, form, [role='alert']",
    )) {
      await expect(element.scrollWidth).toBeLessThanOrEqual(
        element.clientWidth,
      );
    }
    await expect(
      within(dialog).getByText(/When enabled, GitHub tokens are injected/),
    ).toBeVisible();
    await expect(
      within(dialog).queryByText(
        "workspace.toolkits.github.runtimeEnvironmentWarningBody",
      ),
    ).not.toBeInTheDocument();
    const bounds = dialog.getBoundingClientRect();
    for (const control of dialog.querySelectorAll(
      "input, textarea, button, [role='alert'] *",
    )) {
      const controlBounds = control.getBoundingClientRect();
      await expect(controlBounds.right).toBeLessThanOrEqual(bounds.right);
      await expect(controlBounds.left).toBeGreaterThanOrEqual(bounds.left);
    }
  },
} satisfies Story;

export const NarrowEmbeddedGithub = {
  ...MobileEmbeddedGithub,
  parameters: { testViewport: { width: 360, height: 800 } },
} satisfies Story;

export const DesktopEmbeddedGithub = {
  ...MobileEmbeddedGithub,
  parameters: { testViewport: { width: 1280, height: 1000 } },
} satisfies Story;

export const MobileEmbeddedMcp = {
  ...MobileEmbeddedGithub,
  args: {
    ...GenericMcpRequiresName.args,
    embedded: true,
    toolkitTypeLocked: true,
    configurationFields: null,
  },
  play: async ({ canvasElement }) => {
    const dialog = within(canvasElement.ownerDocument.body).getByRole(
      "dialog",
      {
        name: "Toolkit settings",
      },
    );
    await expect(
      within(dialog).getByRole("textbox", { name: "Name" }),
    ).toBeVisible();
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(dialog.clientWidth);
    for (const element of dialog.querySelectorAll(
      ".mantine-Container-root, form",
    )) {
      await expect(element.scrollWidth).toBeLessThanOrEqual(
        element.clientWidth,
      );
    }
  },
} satisfies Story;

export const MobileStandalone = {
  parameters: { testViewport: { width: 390, height: 844 } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("textbox", { name: "Name" }),
    ).toBeVisible();
    const documentElement = canvasElement.ownerDocument.documentElement;
    await expect(documentElement.scrollWidth).toBeLessThanOrEqual(
      documentElement.clientWidth,
    );
  },
} satisfies Story;
