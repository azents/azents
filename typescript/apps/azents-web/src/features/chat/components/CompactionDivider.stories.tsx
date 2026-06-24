import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { CompactionDivider } from "./CompactionDivider";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: CompactionDivider,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof CompactionDivider>;

export default meta;

type Story = StoryObj<typeof meta>;

export const WithSummary = {
  args: {
    content:
      "The previous conversation covered setup, provider configuration, and initial chat UI stories.",
  },
} satisfies Story;

export const WithoutSummary = {
  args: {
    content: null,
  },
} satisfies Story;
