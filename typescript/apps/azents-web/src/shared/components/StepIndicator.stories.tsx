import { rem } from "@mantine/core";
import { StorybookCanvas } from "@/shared/storybook/StorybookCanvas";
import { StepIndicator } from "./StepIndicator";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: StepIndicator,
  decorators: [
    (Story) => (
      <StorybookCanvas maxWidth={rem(360)}>
        <Story />
      </StorybookCanvas>
    ),
  ],
} satisfies Meta<typeof StepIndicator>;

export default meta;

type Story = StoryObj<typeof meta>;

export const FirstStep = {
  args: {
    currentStep: 1,
  },
} satisfies Story;

export const MiddleStep = {
  args: {
    currentStep: 2,
  },
} satisfies Story;

export const FinalStep = {
  args: {
    currentStep: 3,
  },
} satisfies Story;
