import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { McpConfigFieldsContainer } from "../McpConfigFieldsContainer";
import { McpConfigFields } from "./McpConfigFields";
import { ProviderFieldStoryTransport } from "./provider-field-story-fixtures";
import type { McpConfigFieldsProps } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

interface StoryProps extends McpConfigFieldsProps {
  onRequest: (input: unknown) => void;
}
function FieldStory(props: StoryProps): React.ReactElement {
  return <McpConfigFields {...props} />;
}
const meta = {
  title: "Toolkits/Provider fields/Mcp",
  component: FieldStory,
  args: {
    config: { server_url: "https://mcp.example", auth_type: "oauth2" },
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
  },
} satisfies Meta<typeof FieldStory>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Idle: Story = {};
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
      <McpConfigFieldsContainer {...args} />
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
        toolkitType: "mcp",
        toolkitConfigId: "fixture-toolkit",
        config: args.config,
        credentials: null,
      }),
    );
    await expect(
      canvas.findByText(
        /MCP server.*connected|connection.*successful|connection.*succeeded/i,
      ),
    ).resolves.toBeVisible();
  },
};
export const NoHandle: Story = {
  args: { handle: void 0 },
  play: async ({ canvasElement }) => {
    await expect(
      within(canvasElement).queryByRole("button", {
        name: /connection test|test connection/i,
      }),
    ).not.toBeInTheDocument();
  },
};
