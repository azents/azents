import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { GcpConfigFieldsContainer } from "../GcpConfigFieldsContainer";
import { GcpConfigFields } from "./GcpConfigFields";
import { ProviderFieldStoryTransport } from "./provider-field-story-fixtures";
import type { ServiceAccountProviderFieldsProps } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

interface StoryProps extends ServiceAccountProviderFieldsProps {
  onRequest: (input: unknown) => void;
}
function FieldStory(props: StoryProps): React.ReactElement {
  return <GcpConfigFields {...props} />;
}
const meta = {
  title: "Toolkits/Provider fields/Gcp",
  component: FieldStory,
  args: {
    config: { project_id: "fixture-project", services: ["logging"] },
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
    onKeyFileUpload: fn(),
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
      <GcpConfigFieldsContainer {...args} />
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
      <GcpConfigFieldsContainer {...args} />
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
        toolkitType: "gcp",
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
  args: {
    credentials: {
      service_account_key: { client_email: "fixture@example.com" },
    },
    hasCredentials: true,
  },
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{ success: true, message: "Fixture test passed." }}
      onRequest={args.onRequest}
    >
      <GcpConfigFieldsContainer {...args} />
    </ProviderFieldStoryTransport>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Replace Key" }));
    await expect(
      canvas.getByPlaceholderText(/Paste Service Account Key JSON/),
    ).toBeVisible();
  },
};

export const ContainerFileUpload: Story = {
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{ success: true, message: "Fixture test passed." }}
      onRequest={args.onRequest}
    >
      <GcpConfigFieldsContainer {...args} />
    </ProviderFieldStoryTransport>
  ),
  play: async ({ canvasElement, args }) => {
    const input = canvasElement.querySelector('input[type="file"]');
    if (!(input instanceof HTMLInputElement)) {
      throw new Error("Expected provider file input.");
    }
    await userEvent.upload(
      input,
      new File(
        [
          JSON.stringify({
            client_email: "uploaded@example.com",
            fixture: "synthetic",
          }),
        ],
        "fixture.json",
        { type: "application/json" },
      ),
    );
    await waitFor(() =>
      expect(args.onCredentialsChange).toHaveBeenCalledWith({
        service_account_key: {
          client_email: "uploaded@example.com",
          fixture: "synthetic",
        },
      }),
    );
  },
};
