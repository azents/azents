import { Modal } from "@mantine/core";
import { useForm } from "@mantine/form";
import { NextIntlClientProvider } from "next-intl";
import { expect, fn, userEvent, within } from "storybook/test";
import koMessages from "@/i18n/ko-KR-messages";
import { LocaleProvider } from "@/shared/providers/locale";
import {
  projectAwsFields,
  projectGcpFields,
  projectGitHubFormRegistration,
  projectGoogleAnalyticsFields,
  projectKubernetesFields,
  projectNotionFields,
  projectSentryFields,
} from "../provider-config-views";
import { projectToolkitConfig } from "../toolkit-config-projection";
import { AwsConfigFields } from "./AwsConfigFields";
import { BraveSearchFieldsView } from "./BraveSearchFieldsView";
import { EnvVarConfigFields } from "./EnvVarConfigFields";
import { GcpConfigFields } from "./GcpConfigFields";
import { GoogleAnalyticsConfigFields } from "./GoogleAnalyticsConfigFields";
import { KubernetesConfigFields } from "./KubernetesConfigFields";
import { McpConfigFields } from "./McpConfigFields";
import { NotionConfigFields } from "./NotionConfigFields";
import { SentryConfigFields } from "./SentryConfigFields";
import { ToolkitForm } from "./ToolkitForm";
import type { ToolkitFormValues } from "../schemas";
import type { ToolkitConfigFieldsInput } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import type { ReactElement } from "react";

type Provider =
  | "mcp"
  | "aws"
  | "gcp"
  | "google_analytics"
  | "kubernetes"
  | "sentry"
  | "notion"
  | "envvar"
  | "brave_search";
const providers: Record<
  Provider,
  { name: string; config: Record<string, unknown> }
> = {
  mcp: {
    name: "MCP",
    config: { server_url: "https://mcp.example", auth_type: "bearer" },
  },
  aws: { name: "AWS", config: { region: "ap-northeast-2" } },
  gcp: {
    name: "Google Cloud",
    config: { project_id: "example-project", services: ["logging"] },
  },
  google_analytics: { name: "Google Analytics", config: {} },
  kubernetes: {
    name: "Kubernetes",
    config: { clusters: [], read_only: true, denied_kinds: ["Secret"] },
  },
  sentry: { name: "Sentry", config: { enabled_skills: ["inspect"] } },
  notion: { name: "Notion", config: {} },
  envvar: { name: "Environment variables", config: { entries: [] } },
  brave_search: { name: "Brave Search", config: {} },
};
const noOp = (): void => {};

function Fields({
  provider,
  input,
}: {
  provider: Provider;
  input: ToolkitConfigFieldsInput;
}): ReactElement {
  const common = {
    ...input,
    testState: { type: "IDLE" } as const,
    onTestConnection: noOp,
  };
  switch (provider) {
    case "mcp":
      return <McpConfigFields {...common} />;
    case "aws":
      return (
        <AwsConfigFields
          {...common}
          view={projectAwsFields(input.config, input.credentials)}
          showKeyInput
          onShowKeyInput={noOp}
        />
      );
    case "gcp":
      return (
        <GcpConfigFields
          {...common}
          view={projectGcpFields(input.config, input.credentials)}
          showKeyInput
          onShowKeyInput={noOp}
          onKeyFileUpload={noOp}
        />
      );
    case "google_analytics":
      return (
        <GoogleAnalyticsConfigFields
          {...common}
          view={projectGoogleAnalyticsFields(input.config, input.credentials)}
          showKeyInput
          onShowKeyInput={noOp}
          onKeyFileUpload={noOp}
        />
      );
    case "notion":
      return (
        <NotionConfigFields
          {...common}
          view={projectNotionFields(input.config)}
        />
      );
    case "sentry":
      return (
        <SentryConfigFields
          {...common}
          view={projectSentryFields(input.config)}
        />
      );
    case "kubernetes":
      return (
        <KubernetesConfigFields
          {...common}
          view={projectKubernetesFields(input.config, input.credentials)}
          replacingCreds={new Set()}
          storedClusterAuthTypes={new Map()}
          onReplaceCluster={noOp}
        />
      );
    case "envvar":
      return (
        <EnvVarConfigFields
          {...input}
          acknowledged={false}
          onAcknowledgedChange={noOp}
        />
      );
    case "brave_search":
      return (
        <BraveSearchFieldsView
          {...input}
          testState={{ type: "IDLE" }}
          onTestConnection={noOp}
          replacingKey
          onReplaceKey={noOp}
        />
      );
  }
}

interface StoryProps {
  provider: Provider;
  embedded: boolean;
  agentOwned: boolean;
  onSave: (values: ToolkitFormValues) => void;
}
function GuidedForm({
  provider,
  embedded,
  agentOwned,
  onSave,
}: StoryProps): ReactElement {
  const definition = providers[provider];
  const form = useForm<ToolkitFormValues>({
    mode: "controlled",
    initialValues: {
      toolkitType: provider,
      name: "",
      slug: "",
      description: "",
      prompt: "",
      config: definition.config,
      credentials: null,
      enabled: true,
      alwaysExposeTools: false,
    },
  });
  const input: ToolkitConfigFieldsInput = {
    handle: "fixture",
    config: form.values.config,
    credentials: form.values.credentials ?? null,
    hasCredentials: false,
    onConfigChange: (value) => form.setFieldValue("config", value),
    onCredentialsChange: (value) => form.setFieldValue("credentials", value),
  };
  const content = (
    <ToolkitForm
      {...input}
      form={form}
      embedded={embedded}
      agentId={agentOwned ? "fixture-agent" : void 0}
      githubRegistration={projectGitHubFormRegistration(
        null,
        form.values.config,
        form.values.credentials ?? null,
      )}
      configProjection={projectToolkitConfig(provider, form.values.config)}
      configurationFields={<Fields provider={provider} input={input} />}
      toolkitTypeLocked
      formState={{ type: "CREATE" }}
      mutationState={{ type: "IDLE", error: null }}
      isEdit={false}
      backPath="/w/fixture/toolkits"
      toolOptions={[{ value: provider, label: definition.name }]}
      currentToolSlug={provider}
      namePlaceholder={definition.name}
      slugPlaceholder={provider}
      nameRequired={provider === "mcp"}
      showOauthConnection={false}
      oauthConnectionPending={{ connect: false, disconnect: false }}
      onSubmit={form.onSubmit((values) => onSave(values))}
      onToolSelect={noOp}
      onConnectOauth={noOp}
      onDisconnectOauth={noOp}
      onCancel={noOp}
    />
  );
  return embedded ? (
    <Modal opened onClose={noOp} size="lg" title="Toolkit setup">
      {content}
    </Modal>
  ) : (
    content
  );
}
const meta = {
  title: "Toolkits/Guided setup/Real forms",
  component: GuidedForm,
  args: { provider: "mcp", embedded: false, agentOwned: false, onSave: fn() },
} satisfies Meta<typeof GuidedForm>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Mcp: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(
      canvas.getByRole("heading", { name: "1. Prepare your connection" }),
    ).toBeVisible();
    await userEvent.type(
      canvas.getByRole("textbox", { name: "Name" }),
      "Example service",
    );
    const secret = canvas.getByLabelText("Bearer Token");
    await userEvent.type(secret, "synthetic-secret-not-for-summary");
    const review = canvas.getByRole("region", { name: "Settings to save" });
    await expect(within(review).getByText("Example service")).toBeVisible();
    await expect(review).not.toHaveTextContent(
      "synthetic-secret-not-for-summary",
    );
    await userEvent.click(canvas.getByText("Advanced naming and instructions"));
    await userEvent.type(canvas.getByLabelText("Slug"), "example_service");
    await userEvent.click(canvas.getByText("Advanced naming and instructions"));
    await expect(secret).toHaveValue("synthetic-secret-not-for-summary");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Example service",
        slug: "example_service",
      }),
    );
  },
};
export const Aws: Story = { args: { provider: "aws" } };
export const Gcp: Story = { args: { provider: "gcp" } };
export const Analytics: Story = { args: { provider: "google_analytics" } };
export const Kubernetes: Story = { args: { provider: "kubernetes" } };
export const Sentry: Story = { args: { provider: "sentry" } };
export const Notion: Story = { args: { provider: "notion" } };
export const Environment: Story = { args: { provider: "envvar" } };
export const Brave: Story = { args: { provider: "brave_search" } };
export const MobileAgent: Story = {
  args: { provider: "mcp", embedded: true, agentOwned: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement.ownerDocument.body);
    const dialog = canvas.getByRole("dialog");
    await expect(within(dialog).getByText("Only this Agent")).toBeVisible();
    await expect(dialog.scrollWidth).toBeLessThanOrEqual(
      dialog.clientWidth + 1,
    );
  },
};
export const KoreanAws: Story = {
  args: { provider: "aws" },
  decorators: [
    (Story) => (
      <NextIntlClientProvider locale="ko-KR" messages={koMessages}>
        <LocaleProvider locale="ko-KR">
          <Story />
        </LocaleProvider>
      </NextIntlClientProvider>
    ),
  ],
};
export const KoreanNotion: Story = {
  ...KoreanAws,
  args: { provider: "notion", embedded: true },
};
