import { Group, Paper, rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  MessageMetadataFooter,
  MessageMetadataSurface,
} from "./MessageMetadataFooter";
import type { InferenceRunSummary } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const resolvedSummary = {
  run_id: "run-metadata-story",
  run_index: 1,
  status: "completed",
  requested_profile: {
    model_target_label: "Quality",
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
  component: MessageMetadataFooter,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(520)}>
        <MessageMetadataSurface>
          <Paper bg="blue.6" c="white" p="sm" radius="lg">
            Hover this message to reveal its metadata.
          </Paper>
          <Group justify="flex-end" mt={rem(4)}>
            <Story />
          </Group>
        </MessageMetadataSurface>
      </StorybookCanvas>
    ),
  ],
  args: {
    createdAt: "2026-05-19T00:00:00Z",
  },
} satisfies Meta<typeof MessageMetadataFooter>;

export default meta;

type Story = StoryObj<typeof meta>;

export const TimestampOnly: Story = {};

export const AwaitingResolution: Story = {
  args: {
    profile: resolvedSummary.requested_profile,
  },
};

export const ResolvedModel: Story = {
  args: {
    profile: resolvedSummary.requested_profile,
    summary: resolvedSummary,
  },
};
