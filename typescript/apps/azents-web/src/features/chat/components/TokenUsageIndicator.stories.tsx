import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { TokenUsageIndicator } from "./TokenUsageIndicator";
import type { InferenceRunSummary } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const activeRunSummary = {
  run_id: "run-active",
  run_index: 2,
  status: "running",
  requested_profile: {
    model_target_label: "quality",
    reasoning_effort: "high",
  },
  source: "explicit_input",
  resolved_profile: {
    provider: "openai",
    model_identifier: "gpt-5.5",
    model_display_name: "GPT 5.5",
    model_developer: "openai",
  },
  resolved_reasoning_effort: "high",
  effective_context_window_tokens: 128_000,
  effective_auto_compaction_threshold_tokens: 115_200,
  failure_code: null,
  failure_message: null,
} satisfies InferenceRunSummary;

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
    activeRunSummary,
    usage: {
      runId: "run-active",
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

export const HistoricalRunUnavailable = {
  args: {
    activeRunSummary: null,
    usage: {
      runId: "run-terminal",
      promptTokens: 58_000,
      completionTokens: 2_400,
      totalTokens: 60_400,
      cachedTokens: 8_000,
      cacheCreationTokens: 1_200,
      reasoningTokens: 1_100,
    },
  },
} satisfies Story;

export const UnknownProvenance = {
  args: {
    activeRunSummary: null,
    usage: {
      runId: "run-unknown",
      promptTokens: 12_000,
      completionTokens: 800,
      totalTokens: 12_800,
      cachedTokens: null,
      cacheCreationTokens: null,
      reasoningTokens: null,
    },
  },
} satisfies Story;

export const NoUsageYet = {
  args: {
    usage: null,
    activeRunSummary: null,
  },
} satisfies Story;
