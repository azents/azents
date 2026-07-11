import { Group, Paper, rem } from "@mantine/core";
import { expect, fireEvent, userEvent, waitFor, within } from "storybook/test";
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
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.hover(
      canvas.getByText("Hover this message to reveal its metadata."),
    );

    const timestamp = canvasElement.querySelector<HTMLElement>(
      '[data-message-metadata="timestamp"]',
    );
    const separator = canvasElement.querySelector<HTMLElement>(
      '[data-message-metadata="separator"]',
    );
    const model = canvasElement.querySelector<HTMLElement>(
      '[data-message-metadata="model"]',
    );
    if (timestamp === null || separator === null || model === null) {
      throw new Error("Expected timestamp, separator, and model metadata");
    }

    const bottoms = [timestamp, separator, model].map(
      (element) => element.getBoundingClientRect().bottom,
    );
    await expect(
      Math.max(...bottoms) - Math.min(...bottoms),
    ).toBeLessThanOrEqual(1);

    const trigger = canvas.getByRole("button", {
      name: /open inference details/i,
    });
    await fireEvent.click(trigger);
    const page = within(canvasElement.ownerDocument.body);
    const actualModel = await page.findByText("GPT 5.5");
    await waitFor(() => expect(actualModel).toBeVisible());
    await expect(page.getByText("high")).toBeVisible();
    await expect(page.queryByText("Model label")).not.toBeInTheDocument();
    await expect(page.queryByText("Actual model")).not.toBeInTheDocument();
    await expect(page.queryByText("Reasoning effort")).not.toBeInTheDocument();

    const popover = canvasElement.ownerDocument.querySelector<HTMLElement>(
      "[data-message-metadata-popover]",
    );
    if (popover === null) {
      throw new Error("Expected model metadata popover");
    }
    await expect(popover).toBeVisible();
    const popoverStyle = getComputedStyle(popover);
    await expect({
      backgroundColor: popoverStyle.backgroundColor,
      borderRadius: popoverStyle.borderRadius,
      boxShadow: popoverStyle.boxShadow,
      padding: popoverStyle.padding,
    }).toEqual({
      backgroundColor: "rgb(33, 37, 41)",
      borderRadius: "8px",
      boxShadow: "none",
      padding: "5px 10px",
    });
    await expect(getComputedStyle(page.getByText("GPT 5.5")).fontSize).toBe(
      "14px",
    );
  },
};
