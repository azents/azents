import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { RuntimeStatusIndicator } from "./RuntimeStatusIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: RuntimeStatusIndicator,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof RuntimeStatusIndicator>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Initializing = {
  args: {
    status: "initializing",
  },
} satisfies Story;

export const Ready = {
  args: {
    status: "ready",
  },
} satisfies Story;

export const Error = {
  args: {
    status: "error",
  },
} satisfies Story;
