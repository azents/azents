import { Group, rem, Stack, Text } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { AgentAvatar } from "./AgentAvatar";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

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
