import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { KubernetesConfigFieldsContainer } from "../KubernetesConfigFieldsContainer";
import { KubernetesConfigFields } from "./KubernetesConfigFields";
import { ProviderFieldStoryTransport } from "./provider-field-story-fixtures";
import type { KubernetesConfigFieldsProps } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

interface StoryProps extends KubernetesConfigFieldsProps {
  onRequest: (input: unknown) => void;
}
function FieldStory(props: StoryProps): React.ReactElement {
  return <KubernetesConfigFields {...props} />;
}
const meta = {
  title: "Toolkits/Provider fields/Kubernetes",
  component: FieldStory,
  args: {
    config: {
      clusters: [
        {
          name: "fixture-cluster",
          auth_type: "token",
          default_namespace: "default",
          context: null,
          api_server: "https://cluster.example",
          cluster_name: null,
          region: null,
          project_id: null,
        },
      ],
    },
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
    replacingCreds: new Set<string>(),
    storedClusterAuthTypes: new Map([["fixture-cluster", "token"]]),
    onReplaceCluster: fn(),
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
  render: (args) => (
    <ProviderFieldStoryTransport
      response={{ success: true, message: "Unused fixture response." }}
      errorMessage="Fixture transport failed."
      onRequest={args.onRequest}
    >
      <KubernetesConfigFieldsContainer {...args} />
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
      <KubernetesConfigFieldsContainer {...args} />
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
        toolkitType: "kubernetes",
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
export const StoredClusterReplacement: Story = {
  args: {
    hasCredentials: true,
    storedClusterAuthTypes: new Map([["fixture-cluster", "token"]]),
  },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(
      within(canvasElement).getByRole("button", {
        name: "Replace credentials",
      }),
    );
    await expect(args.onReplaceCluster).toHaveBeenCalledWith("fixture-cluster");
  },
};
