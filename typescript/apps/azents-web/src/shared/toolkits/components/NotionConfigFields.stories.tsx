import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { NotionConfigFieldsContainer } from "../NotionConfigFieldsContainer";
import { NotionConfigFields } from "./NotionConfigFields";
import { ProviderFieldStoryTransport } from "./provider-field-story-fixtures";
import type { SimpleProviderFieldsProps } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

interface StoryProps extends SimpleProviderFieldsProps {
  onRequest: (input: unknown) => void;
}
function FieldStory(props: StoryProps): React.ReactElement {
  return <NotionConfigFields {...props} />;
}
const meta = {
  title: "Toolkits/Provider fields/Notion",
  component: FieldStory,
  args: {
    config: { timeout: 30 },
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
      <NotionConfigFieldsContainer {...args} />
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
        toolkitType: "notion",
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
