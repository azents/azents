import { Box, rem } from "@mantine/core";
import { Header } from "./Header";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: Header,
  decorators: [
    (Story) => (
      <Box style={{ minHeight: rem(160) }}>
        <Story />
      </Box>
    ),
  ],
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof Header>;

export default meta;

type Story = StoryObj<typeof meta>;

export const TopOfPage = {} satisfies Story;
