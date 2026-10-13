import { Button, Text } from "@mantine/core";
import { GitHubWizardSection } from "./GitHubWizardSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
const meta = {
  component: GitHubWizardSection,
  args: {
    id: "section-example",
    number: 3,
    title: "Verify your connection",
    subtitle: "Check the account or App before continuing.",
    children: <Text size="sm">Actual connection controls appear here.</Text>,
  },
} satisfies Meta<typeof GitHubWizardSection>;
export default meta;
type Story = StoryObj<typeof meta>;
export const Input: Story = {};
export const Complete: Story = { args: { complete: true } };
export const Locked: Story = {
  args: { disabled: true, children: <Button>Save pending</Button> },
};
