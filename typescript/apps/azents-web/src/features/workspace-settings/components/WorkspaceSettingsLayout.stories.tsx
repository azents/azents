import { Box, rem, Text } from "@mantine/core";
import { WorkspaceSettingsLayout } from "./WorkspaceSettingsLayout";
import type { WorkspaceResponse } from "@azents/public-client";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const workspace: WorkspaceResponse = {
  name: "Platform Engineering",
  handle: "platform-engineering",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

const meta = {
  component: WorkspaceSettingsLayout,
  decorators: [
    (Story) => (
      <Box h={rem(640)}>
        <Story />
      </Box>
    ),
  ],
  args: {
    workspace,
    backTarget: "settings",
    children: (
      <Box p="md">
        <Text>Workspace settings content</Text>
      </Box>
    ),
  },
} satisfies Meta<typeof WorkspaceSettingsLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Detail = {} satisfies Story;

export const Overview = {
  args: { backTarget: "workspace" },
} satisfies Story;
