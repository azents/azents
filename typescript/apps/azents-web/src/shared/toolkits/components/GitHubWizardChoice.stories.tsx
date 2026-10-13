import { IconUser } from "@tabler/icons-react";
import { fn } from "storybook/test";
import { GitHubWizardChoice } from "./GitHubWizardChoice";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GitHubWizardChoice,
  args: {
    title: "Connect with my GitHub account",
    description: "Use your account for GitHub work.",
    icon: <IconUser size="1em" />,
    selected: false,
    onSelect: fn(),
  },
} satisfies Meta<typeof GitHubWizardChoice>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Unselected: Story = {};
export const Selected: Story = { args: { selected: true } };
export const LongText: Story = {
  args: {
    title:
      "Connect with the account you use for your organization's GitHub work",
    description:
      "A longer label and explanation should wrap without changing the reserved icon or selection slots.",
    selected: true,
  },
};
