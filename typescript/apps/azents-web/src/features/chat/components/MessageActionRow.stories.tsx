import { ActionIcon, rem } from "@mantine/core";
import { IconPencil, IconTrash } from "@tabler/icons-react";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { MessageActionRow } from "./MessageActionRow";
import { MessageMetadataSurface } from "./MessageMetadataFooter";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: MessageActionRow,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(560)}>
        <MessageMetadataSurface>
          <Story />
        </MessageMetadataSurface>
      </StorybookCanvas>
    ),
  ],
  args: {
    content: "Please continue with this context.",
    createdAt: "2026-05-19T00:00:00Z",
    align: "user",
  },
} satisfies Meta<typeof MessageActionRow>;

export default meta;

type Story = StoryObj<typeof meta>;

export const User: Story = {
  args: {
    inferenceProfile: {
      model_target_label: "quality",
      reasoning_effort: "high",
    },
  },
};

export const UserEditable: Story = {
  args: {
    inferenceProfile: {
      model_target_label: "quality",
      reasoning_effort: "high",
    },
    additionalActions: (
      <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Edit">
        <IconPencil size={rem(14)} />
      </ActionIcon>
    ),
  },
};

export const UserPendingDeletion: Story = {
  args: {
    inferenceProfile: {
      model_target_label: "quality",
      reasoning_effort: "high",
    },
    additionalActions: (
      <ActionIcon variant="subtle" color="gray" size="sm" aria-label="Delete">
        <IconTrash size={rem(14)} />
      </ActionIcon>
    ),
  },
};

export const Assistant: Story = {
  args: {
    align: "assistant",
    inferenceProfile: null,
  },
};
