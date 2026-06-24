import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AppLogo } from "./AppLogo";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: AppLogo,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof AppLogo>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;

export const Linked = {
  args: {
    href: "/workspaces",
  },
} satisfies Story;
