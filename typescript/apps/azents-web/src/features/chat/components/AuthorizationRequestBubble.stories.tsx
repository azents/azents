import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AuthorizationRequestBubble } from "./AuthorizationRequestBubble";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const handleAuthorized = (): void => {};

const meta = {
  component: AuthorizationRequestBubble,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof AuthorizationRequestBubble>;

export default meta;

type Story = StoryObj<typeof meta>;

export const GitHubAuthorization = {
  args: {
    toolkitName: "GitHub",
    authorizationUrl: "https://example.com/oauth/github",
    onAuthorized: handleAuthorized,
  },
} satisfies Story;
