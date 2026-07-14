import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { TokenUsageIndicator } from "./TokenUsageIndicator";
import type { ChatLiveRunState } from "../types";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const activeRun = {
  run_id: "run-active",
  phase: "streaming_model",
  status: "running",
  inferenceProfile: {
    model_target_label: "quality",
    model_display_name: "GPT 5.5",
    reasoning_effort: "high",
  },
  modelCallStartedAt: new Date(Date.now() - 12_000).toISOString(),
  retry: null,
} satisfies ChatLiveRunState;

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
    activeRun,
    usage: {
      runId: "run-active",
      inferenceProfile: null,
      effectiveContextWindowTokens: 270_000,
      effectiveAutoCompactionThresholdTokens: 243_000,
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

export const ActiveRun = {} satisfies Story;

export const HistoricalRunWithDurableProvenance = {
  args: {
    activeRun: null,
    usage: {
      runId: "run-terminal",
      inferenceProfile: {
        model_target_label: "planning",
        model_display_name: "GPT 5.6 Sol",
        reasoning_effort: "future-ultra",
      },
      effectiveContextWindowTokens: 128_000,
      effectiveAutoCompactionThresholdTokens: 102_400,
      promptTokens: 58_000,
      completionTokens: 2_400,
      totalTokens: 60_400,
      cachedTokens: 8_000,
      cacheCreationTokens: 1_200,
      reasoningTokens: 1_100,
    },
  },
} satisfies Story;

export const HistoricalRunUnavailable = {
  args: {
    activeRun: null,
    usage: {
      runId: "run-terminal",
      inferenceProfile: null,
      effectiveContextWindowTokens: null,
      effectiveAutoCompactionThresholdTokens: null,
      promptTokens: 58_000,
      completionTokens: 2_400,
      totalTokens: 60_400,
      cachedTokens: 8_000,
      cacheCreationTokens: 1_200,
      reasoningTokens: 1_100,
    },
  },
} satisfies Story;

export const NoUsageYet = {
  args: {
    usage: null,
    activeRun: null,
  },
} satisfies Story;
