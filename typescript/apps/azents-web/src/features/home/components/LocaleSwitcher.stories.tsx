import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { LocaleSwitcher } from "./LocaleSwitcher";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: LocaleSwitcher,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof LocaleSwitcher>;

export default meta;

type Story = StoryObj<typeof meta>;

export const CurrentLocale = {} satisfies Story;
