import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ChatPreview } from "./ChatPreview";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: ChatPreview,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof ChatPreview>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
