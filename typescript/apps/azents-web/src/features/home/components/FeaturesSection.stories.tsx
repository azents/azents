import { FeaturesSection } from "./FeaturesSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: FeaturesSection,
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof FeaturesSection>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
