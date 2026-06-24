import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { TurnDivider } from "./TurnDivider";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: TurnDivider,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof TurnDivider>;

export default meta;

type Story = StoryObj<typeof meta>;

export const UsageOnly = {
  args: {
    usage: {
      prompt_tokens: 4800,
      completion_tokens: 640,
      cached_tokens: 1200,
      cache_creation_tokens: 900,
      reasoning_tokens: 320,
      total_tokens: 5760,
    },
  },
} satisfies Story;

export const CompactUsage = {
  args: {
    usage: {
      prompt_tokens: 1200,
      completion_tokens: 300,
      total_tokens: 1500,
    },
  },
} satisfies Story;
