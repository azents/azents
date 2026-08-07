import { rem } from "@mantine/core";
import { fn } from "storybook/test";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { NewSessionScopeSelector } from "./NewSessionScopeSelector";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: NewSessionScopeSelector,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(320)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
  args: {
    value: "team",
    onChange: fn(),
  },
} satisfies Meta<typeof NewSessionScopeSelector>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Team = {} satisfies Story;

export const User = {
  args: {
    value: "user",
  },
} satisfies Story;
