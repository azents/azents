import { CtaSection } from "./CtaSection";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";

const meta = {
  component: CtaSection,
  parameters: {
    layout: "fullscreen",
  },
} satisfies Meta<typeof CtaSection>;

export default meta;

type Story = StoryObj<typeof meta>;

export const Default = {} satisfies Story;
