import { Group, SimpleGrid, Stack, Text } from "@mantine/core";
import { expect, within } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { ToolkitTypeIcon } from "./ToolkitTypeIcon";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const types = [
  "github",
  "notion",
  "sentry",
  "aws",
  "google_analytics",
  "gcp",
  "brave_search",
  "kubernetes",
  "mcp",
  "envvar",
  "test-only-provider",
];
const meta = {
  component: ToolkitTypeIcon,
  decorators: [
    (Story) => (
      <StorybookCanvas>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: { toolkitType: "github" },
} satisfies Meta<typeof ToolkitTypeIcon>;
export default meta;
type Story = StoryObj<typeof meta>;
export const AllProviders = {
  render: () => (
    <SimpleGrid cols={{ base: 2, sm: 4 }}>
      {types.map((type) => (
        <Stack key={type} gap="xs">
          <Group>
            <ToolkitTypeIcon toolkitType={type} size={40} />
            <ToolkitTypeIcon toolkitType={type} size={28} />
          </Group>
          <Text size="xs">{type}</Text>
        </Stack>
      ))}
    </SimpleGrid>
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const type of types) {
      await expect(canvas.getByText(type)).toBeVisible();
    }
  },
} satisfies Story;
