import { Group, Paper, rem } from "@mantine/core";
import { expect, fireEvent, userEvent, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import {
  MessageMetadataFooter,
  MessageMetadataSurface,
} from "./MessageMetadataFooter";
import type { AppliedInferenceProfile } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const appliedProfile = {
  model_target_label: "Quality",
  model_display_name: "GPT 5.5",
  reasoning_effort: "high",
} satisfies AppliedInferenceProfile;

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

export const ResolvedModel: Story = {
  args: {
    profile: appliedProfile,
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
    await expect(page.getByText("GPT 5.5")).toBeVisible();
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
    await expect(
      getComputedStyle(within(popover).getByText("GPT 5.5")).fontSize,
    ).toBe("14px");
  },
};
