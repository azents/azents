import { GitHubWizardCallbackHelp } from "./GitHubWizardCallbackHelp";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GitHubWizardCallbackHelp,
  args: {
    optional: false,
    availability: {
      type: "READY",
      userAccount: "configured",
      installation: "configured",
      callbackUrl: "https://azents.example/oauth/github/callback",
    },
  },
} satisfies Meta<typeof GitHubWizardCallbackHelp>;
export default meta;
type Story = StoryObj<typeof meta>;
export const PersonalCallback: Story = {};
export const AppCallbackOptional: Story = { args: { optional: true } };
export const Unavailable: Story = {
  args: {
    availability: {
      type: "READY",
      userAccount: "absent",
      installation: "absent",
      callbackUrl: null,
    },
  },
};
export const Loading: Story = { args: { availability: { type: "LOADING" } } };
