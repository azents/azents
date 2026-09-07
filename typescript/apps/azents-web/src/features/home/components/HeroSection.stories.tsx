import { HeroSection } from "./HeroSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: HeroSection,
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof HeroSection>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
