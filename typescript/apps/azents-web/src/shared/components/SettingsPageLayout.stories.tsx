import { Box, rem, Text } from "@mantine/core";
import { SettingsPageLayout } from "./SettingsPageLayout";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: SettingsPageLayout,
  decorators: [
    (Story) => (
      <Box h={rem(520)}>
        <Story />
      </Box>
    ),
  ],
  args: {
    header: (
      <Box p="md">
        <Text fw={600}>Workspace identity</Text>
      </Box>
    ),
    backHref: "/w/acme/settings",
    backLabel: "Back to settings",
    children: (
      <Box p="md">
        <Text>Focused settings content</Text>
      </Box>
    ),
  },
} satisfies Meta<typeof SettingsPageLayout>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
