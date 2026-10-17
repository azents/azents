import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { AwsConfigFieldsContainer } from "../AwsConfigFieldsContainer";
import { projectAwsFields } from "../provider-config-views";
import { AwsConfigFields } from "./AwsConfigFields";
import { ProviderFieldStoryTransport } from "./provider-field-story-fixtures";
import type { CredentialProviderFieldsProps } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

type StoryProps = Exclude<CredentialProviderFieldsProps, { owner: "user" }> & {
  onRequest: (input: unknown) => void;
};
function FieldStory(props: StoryProps): React.ReactElement {
  return (
    <AwsConfigFields
      {...props}
      view={projectAwsFields(props.config, props.credentials)}
    />
  );
}
const meta = {
  title: "Toolkits/Provider fields/Aws",
  component: FieldStory,
  args: {
    config: { region: "us-east-1" },
    onConfigChange: fn(),
    credentials: null,
    onCredentialsChange: fn(),
    hasCredentials: false,
    handle: "fixture-workspace",
    agentId: "fixture-agent",
    toolkitConfigId: "fixture-toolkit",
    testState: { type: "IDLE" },
    onTestConnection: fn(),
    onRequest: fn(),
    showKeyInput: true,
    onShowKeyInput: fn(),
  },
} satisfies Meta<typeof FieldStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Idle: Story = {};
export const TransportError: Story = {
  args: { testState: { type: "ERROR", message: "Fixture transport failed." } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("Fixture transport failed."),
    ).toBeVisible();
  },
};
export const ContainerTransportError: Story = {
  args: { hasCredentials: true },
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{ success: true, message: "Unused fixture response." }}
      errorMessage="Fixture transport failed."
      onRequest={args.onRequest}
    >
      <AwsConfigFieldsContainer {...args} />
    </ProviderFieldStoryTransport>
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /connection test|test connection/i }),
    );
    await expect(
      canvas.findByText("Fixture transport failed."),
    ).resolves.toBeVisible();
    await expect(args.onRequest).toHaveBeenCalledTimes(1);
  },
};
export const Testing: Story = {
  args: { testState: { type: "TESTING" } },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByRole("button", {
        name: /connection test|test connection/i,
      }),
    ).toHaveAttribute("data-loading", "true");
  },
};
export const SuccessfulTest: Story = {
  args: {
    testState: {
      type: "RESULT",
      result: {
        success: true,
        message: "Fixture success.",
        discoveredAuthUrl: "https://auth.example",
        discoveredTokenUrl: "https://token.example",
        supportsDcr: true,
      },
    },
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Fixture success.")).toBeVisible();
  },
};
export const RejectedTest: Story = {
  args: {
    testState: {
      type: "RESULT",
      result: { success: false, message: "Fixture rejected." },
    },
  },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).getByText("Fixture rejected."),
    ).toBeVisible();
  },
};
export const ContainerTest: Story = {
  args: { hasCredentials: true },
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{
        success: true,
        message: "Fixture test passed.",
        discovered_auth_url: "https://auth.example",
        discovered_token_url: "https://token.example",
        supports_dcr: true,
      }}
      onRequest={args.onRequest}
    >
      <AwsConfigFieldsContainer {...args} />
    </ProviderFieldStoryTransport>
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(
      canvas.getByRole("button", { name: /connection test|test connection/i }),
    );
    await waitFor(() =>
      expect(args.onRequest).toHaveBeenCalledWith({
        handle: "fixture-workspace",
        agentId: "fixture-agent",
        toolkitType: "aws",
        toolkitConfigId: "fixture-toolkit",
        config: args.config,
        credentials: null,
      }),
    );
    await expect(
      canvas.findByText("Fixture test passed."),
    ).resolves.toBeVisible();
  },
};
export const ExistingCredentials: Story = {
  args: { hasCredentials: true, showKeyInput: false },
};

export const ContainerCredentialReplacement: Story = {
  args: { credentials: null, hasCredentials: true },
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{ success: true, message: "Fixture test passed." }}
      onRequest={args.onRequest}
    >
      <AwsConfigFieldsContainer {...args} />
    </ProviderFieldStoryTransport>
  ),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/Credentials are saved/)).toBeVisible();
    await expect(
      canvas.queryByRole("textbox", { name: "Access Key ID" }),
    ).not.toBeInTheDocument();
    await expect(args.onCredentialsChange).not.toHaveBeenCalled();
    await userEvent.click(
      canvas.getByRole("button", { name: "Replace Credentials" }),
    );
    await expect(
      canvas.getByRole("textbox", { name: "Access Key ID" }),
    ).toBeVisible();
    await expect(args.onCredentialsChange).not.toHaveBeenCalled();
  },
};
