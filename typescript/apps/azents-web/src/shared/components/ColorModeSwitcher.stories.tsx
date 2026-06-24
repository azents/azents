import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ColorModeSwitcher } from "./ColorModeSwitcher";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ColorModeSwitcher,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ColorModeSwitcher>;

export default meta;

type Story = StoryObj<typeof meta>;

export const CurrentPreference = {} satisfies Story;
