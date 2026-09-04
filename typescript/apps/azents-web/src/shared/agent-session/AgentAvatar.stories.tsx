import { Group, rem, Stack, Text } from "@mantine/core";
import { AgentAvatar } from "@/shared/agent-session/AgentAvatar";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import type { UploadedImage } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const responsiveAvatar = {
  filename: "azents-icon-dark-tile.png",
  default: {
    url: "/brand/azents/azents-icon-dark-tile.png#large",
    width: 512,
    height: 512,
  },
  thumbnails: {
    small: {
      url: "/brand/azents/azents-icon-dark-tile.png#small",
      width: 128,
      height: 128,
    },
    medium: {
      url: "/brand/azents/azents-icon-dark-tile.png#medium",
      width: 256,
      height: 256,
    },
    large: {
      url: "/brand/azents/azents-icon-dark-tile.png#large",
      width: 512,
      height: 512,
    },
  },
  uploaded_at: "2026-09-04T00:00:00Z",
} satisfies UploadedImage;

const meta = {
  component: AgentAvatar,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof AgentAvatar>;

export default meta;

type Story = StoryObj<typeof meta>;

export const InitialOnly = {
  args: {
    name: "Azents Assistant",
    size: 56,
    radius: "xl",
  },
} satisfies Story;

export const DeterministicColors = {
  args: {
    name: "Planner",
  },
  render: () => (
    <Stack gap="sm">
      {["Planner", "Reviewer", "Operator", "Researcher", "Debugger"].map(
        (name) => (
          <Group key={name} gap="sm">
            <AgentAvatar name={name} radius="xl" />
            <Text size="sm">{name}</Text>
          </Group>
        ),
      )}
    </Stack>
  ),
} satisfies Story;

export const ResponsiveImageTiers = {
  args: {
    name: "Azents Assistant",
    avatar: responsiveAvatar,
    size: 96,
    radius: "xl",
  },
} satisfies Story;
