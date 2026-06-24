import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { TokenUsageIndicator } from "./TokenUsageIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: TokenUsageIndicator,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    modelName: "Main · GPT 5.5",
    effectiveContextWindowTokens: 128_000,
    autoCompactionThresholdTokens: 115_200,
    usage: {
      promptTokens: 47_043,
      completionTokens: 1_200,
      totalTokens: 48_243,
      cachedTokens: 12_000,
      cacheCreationTokens: 2_400,
      reasoningTokens: 800,
    },
  },
} satisfies Meta<typeof TokenUsageIndicator>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Normal = {} satisfies Story;

export const NearLimit = {
  args: {
    effectiveContextWindowTokens: 64_000,
    autoCompactionThresholdTokens: 57_600,
    usage: {
      promptTokens: 58_000,
      completionTokens: 2_400,
      totalTokens: 60_400,
      cachedTokens: 8_000,
      cacheCreationTokens: 1_200,
      reasoningTokens: 1_100,
    },
  },
} satisfies Story;

export const UnknownLimit = {
  args: {
    effectiveContextWindowTokens: null,
    autoCompactionThresholdTokens: null,
  },
} satisfies Story;

export const NoUsageYet = {
  args: {
    usage: null,
  },
} satisfies Story;
