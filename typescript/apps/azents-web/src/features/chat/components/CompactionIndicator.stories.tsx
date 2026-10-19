import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { CompactionIndicator } from "./CompactionIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  tags: ["ci-contract"],
  component: CompactionIndicator,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof CompactionIndicator>;

export default meta;

type Story = StoryObj<typeof meta>;

export const InProgress = {} satisfies Story;
